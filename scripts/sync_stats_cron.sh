#!/bin/bash
# Sync YouTube stats - run every 6 hours
docker exec jb_apulv3-worker-upload-1 python3 -c "
import os, psycopg2, psycopg2.extras
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import httplib2

DB_URL = os.environ.get('DATABASE_URL', 'postgresql://jb_user:change-me@db:5432/jb_apulv3').replace('postgresql+asyncpg://', 'postgresql://')
conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()
cur.execute('SELECT id, name, access_token, refresh_token FROM channels WHERE access_token IS NOT NULL')
for ch in cur.fetchall():
    try:
        creds = Credentials(token=ch['access_token'], refresh_token=ch['refresh_token'], token_uri='https://oauth2.googleapis.com/token', client_id=os.environ.get('GOOGLE_CLIENT_ID', ''), client_secret=os.environ.get('GOOGLE_CLIENT_SECRET', ''))
        if creds.expired and creds.refresh_token:
            creds.refresh(httplib2.Http())
            cur.execute('UPDATE channels SET access_token=%s WHERE id=%s', (creds.token, ch['id']))
            conn.commit()
        youtube = build('youtube', 'v3', credentials=creds)
        response = youtube.channels().list(part='statistics', mine=True).execute()
        if response.get('items'):
            stats = response['items'][0]['statistics']
            cur.execute('UPDATE channels SET subscriber_count=%s, total_views=%s, video_count=%s WHERE id=%s', (int(stats.get('subscriberCount', 0)), int(stats.get('viewCount', 0)), int(stats.get('videoCount', 0)), ch['id']))
            conn.commit()
    except: pass
cur.close()
conn.close()
" >> /var/www/jb_apulv3/storage/logs/youtube_stats.log 2>&1
