import os
import requests
import pandas
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import smtplib
from pymongo import MongoClient
import base64
import PyPDF2
from dotenv import load_dotenv, find_dotenv
from io import BytesIO
from flask import send_file
import io
import math


_ = load_dotenv(find_dotenv()) # read local .env file
api_url = os.environ['GEMINI_API_URL']
api_key = os.environ['GEMINI_API_KEY']

database_url = os.environ['MONGODB_URI']
mongo_client = MongoClient(database_url)

db = mongo_client['referal_agent_db']
collection = db['job_details']

# Flask app definition
app = Flask(__name__)
CORS(app)

# Tracking pixel endpoint: updates 'view' and returns 1x1 transparent GIF
@app.route('/track_view')
def track_view():
    email = request.args.get('email')
    if email:
        collection.update_one({'email_To': email}, {'$set': {'view': 1}})
    # 1x1 transparent GIF
    pixel = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
    return send_file(io.BytesIO(pixel), mimetype='image/gif')



def sanitize_record(record):
    for k, v in record.items():
        if isinstance(v, float) and math.isnan(v):
            record[k] = ""
    return record

@app.route('/get_views', methods=['GET'])
def get_views():
    try:
        records = list(collection.find({}, {'_id': 0}))
        records = [sanitize_record(r) for r in records]
        return jsonify(records), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500