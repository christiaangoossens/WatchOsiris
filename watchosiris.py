#################################
# WatchOsiris utility           #
# By Christiaan Goossens, 2018  #
#################################

# IMPORTS
import click
import requests as req
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup as bs
import csv
import os
import time
import smtplib
import email
from email.mime.text import MIMEText

############# VARIABLES ######################
# TODO:: Edit these

userId = 'your-number-like-20170000-that-you-use-to-login-to-osiris'
password = 'your-password'

smtp_server = 'your-mail-server'
smtp_port = '587'
smtp_username = 'your-email-or-login-username'
smtp_password = 'some-password'

from_mail = 'your-email'
to_mail = 'your-email'

file = 'grades.csv' 

############# PRESET VARIABLES ###############
# Don't edit these unless necessary

os_home = 'http://osiris.tue.nl'
os_full = 'https://osiris.tue.nl/osiris_student_tueprd/'
saml_rp_url = 'https://osiris.tue.nl:443/osirissaml/saml2/acs/tue-prd-osiris-student'

s = req.Session()
pd.set_option('display.expand_frame_repr', False)

############## FUNCTIONS ######################

# Login with ADFS
def login(debug = False):
    # This should go out to ADFS for signin
    global s
    r = s.get(os_home)
    page = bs(r.text, 'html.parser')

    # If timeout
    if (page.find('title').text == 'OSIRIS - Timeout'):
        s = req.Session()
        r = s.get(os_home)
        page = bs(r.text, 'html.parser')
    
    # Extra page with maintenance notification
    if (page.find('title').text == 'OSIRIS - Inloggen'):
        authForm = page.find(id='loginForm')
        adfsUrl = os_full + authForm.get('action')
        token = page.find(id='requestToken').get('value')
        payload = {'startUrl': 'Personalia.do', 'inPortal': '', 'callDirect': '', 'requestToken': token, 'event': 'login'}
        p = s.post(adfsUrl, data=payload)
        page = bs(p.text, 'html.parser')

    # DEFAULT ADFS LOGIN PAGE
    if (page.find('title').text == 'Sign In'):
        authForm = page.find(id='loginArea').form
        adfsUrl = 'https://sts.tue.nl' + authForm.get('action')

        payload = {'UserName': 'TUe\\' + userId, 'Password': password, 'AuthMethod': 'FormsAuthentication'}
        p = s.post(adfsUrl, data=payload)

        page = bs(p.text, 'html.parser')
        if (page.find(id='errorText') != None):
                print(page.find(id='errorText').text)
                return

        # Success? Then we post to Osiris
        if (page.body.form.get('action') != saml_rp_url):
                print("No, something went wrong with ADFS, the page was incorrect.")
                return
    
    # ADFS FORM POST REDIRECT PAGE
    if (page.find('title').text == 'Working...'):
        samlResponse = page.find('input', {'name': 'SAMLResponse'}).get('value')
        relayState = page.find('input', {'name': 'RelayState'}).get('value')

        payload = {'SAMLResponse': samlResponse, 'RelayState': relayState }
        o = s.post(saml_rp_url, data=payload)

    # If this succeeds, we're in!
    # do not get main url because it redirect to the maintenance notification
    o = s.get(os_full + 'ToonPersonalia.do')
    op = bs(o.text, 'html.parser')

    if (op.find('title').text != 'OSIRIS - Personalia'):
        print('Failed getting OSIRIS, something went wrong')
        return

    # We're in!
    tableValues = op.findAll('span', {'class':'psbTekst'})
    naam = tableValues[2].text
    nummer = tableValues[1].text

    if debug:
        print('=================================')
        print()
        print('CONNECTED TO OSIRIS')
        print("Welcome `" + naam + '` with student number: ' + nummer)
        print()
        print('=================================')
        print()

# Get cijfers
def getCijfers(debug = False):
    p = s.get(os_full + 'ToonResultaten.do')
    page = bs(p.text, 'html.parser')
	
    if (page.find('title').text != 'OSIRIS - Resultaten'):
       login(debug)
       p = s.get(os_full + 'ToonResultaten.do')
       page = bs(p.text, 'html.parser')

    table = page.find('table', {'class': 'OraTableContent'})
    rows = table.find_all('tr')
    cijfers = [];

    for row in rows:
        columns = row.find_all('td')
        if (len(columns) != 0):
            # if it's not the header row
            date = columns[0].span.text
            course = columns[1].span.text
            courseName = columns[2].span.text

            try:
              gradeType = columns[3].span.text
            except AttributeError:
              gradeType = ''

            teacher = columns[4].span.text

            try:
              weight = columns[5].span.text
            except AttributeError:
              weight = ''

            grade = columns[7].span.text
            enterDate = columns[9].span.text

            cijfers.append({'date': date, 'course': course, 'courseName': courseName, 'type': gradeType, 'teacher': teacher, 'weight': weight, 'grade': grade, 'enterDate': enterDate})

    # Create DataFrame
    df = pd.DataFrame(data=cijfers)

    # Clean up the data
    df = df.apply(lambda x: x.str.strip()).replace('', np.nan)
    df['weight'] = df['weight'].apply(pd.to_numeric, errors='coerce')

    # Return
    return df

def saveCijfers(df):
    if os.path.isfile(file):
        try:
            old_df = pd.read_csv(file)
            concat_df = pd.concat([df, old_df]).drop_duplicates().reset_index(drop=True)
            concat_df.to_csv(file, index=False, quoting=csv.QUOTE_NONNUMERIC)
        except pd.errors.EmptyDataError:
            df.to_csv(file, index=False, quoting=csv.QUOTE_NONNUMERIC)

    else:
        df.to_csv(file, index=False, quoting=csv.QUOTE_NONNUMERIC)

    print("Saved grades to disk")

def detectNew(df):
    old_df = pd.read_csv(file)
    concat_df = pd.concat([df, old_df]).drop_duplicates().reset_index(drop=True)
    newRows = []

    for index, row in concat_df.iterrows():
        rl = row.tolist();

        # check if we've found the old table
        if (rl == old_df.iloc[0].tolist()):
            break

        newRows.append(rl)

    # Return the array with new rows
    return newRows

# Notify
def sendNotifications(grades):
    for grade in grades:
        body = "You got a new grade for " + grade[0] + ": " + grade[1] + ", with the subject of: <i>" + grade[6] + "</i> and a weight of: " + str(grade[7]) + ". You got the following grade: <b>" + grade[4] + "</b>"
        subject = "You got a new grade for " + grade[0]        
        mail(subject, body)

    print('Notifications sent!')

def sendErrorNotice(error):
    mail("Encountered error", "The error was: " + error)

def mail(subject, body):
    # Send an email
    if smtp_password == 'some-password':
        print("SMTP credentials not found, not sending notification!")
        exit()

    server = smtplib.SMTP(smtp_server, smtp_port)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(smtp_username, smtp_password)

    msg = MIMEText(body, 'html');

    msg['From'] = 'WatchOsiris <' + from_mail + '>'
    msg['To'] = to_mail
    msg['Subject'] = subject
    msg["Date"] = email.utils.formatdate()

    msg_full = msg.as_string()

    server.sendmail(from_mail, to_mail, msg_full)

############# START OF PROGRAM ###############

# WATCH
@click.group()
def cli():
    pass

@cli.command()
@click.option('--notify', help='Enable email notifications', is_flag=True)
def watch(notify):
    """Watch Osiris for changes and save changes to disk."""

    if not os.path.isfile(file):
        print("Please run the get command first to get the initial data and test if everything is alright")
        return

    try:
        while True:
            try:
                # Contact Osiris and get changes to save them
                print('Contacting Osiris for changes.')
                df = getCijfers()

                if (notify):
                    newRows = detectNew(df)
                    print('Checking for differences: ', newRows)

                    if (len(newRows) > 0):
                        print("Found differences, sending notifications! ;)")
                        sendNotifications(newRows)

                saveCijfers(df)

                print('Done, waiting..')
                print()
            except Exception as e:
                print('Something failed')
                sendErrorNotice(repr(e))
                
                # Reset session
                s = req.Session()
            
            time.sleep(300) # 5 minutes
    except KeyboardInterrupt:
        print('Manual break by user')

@cli.command()
def testNotify():
    """Allows for testing the email notifications"""
    sendNotifications([['2IAB0', 'Data Analytics for Engineers', '01-01-1900', '01-01-1900', '10', 'prof. Warbol', 'Toets', 100.0]])

# LOOKUP
@cli.command()
def lookup():
    """Returns saved CSV data in a table."""

    if not os.path.isfile(file):
        print("No data found")
        return

    df = pd.read_csv(file)
    print(df)

# GET
@cli.command()
def get():
    """Gets data directly from Osiris for debugging"""

    df = getCijfers(True)
    saveCijfers(df)

# RUN INIT
# Run default command if none is specified
if __name__ == '__main__':
    cli()
