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

# Upload endpoint: receives Excel and PDF, stores Excel in MongoDB, returns resume as base64
@app.route('/upload', methods=['POST'])
def upload():
    try:
        excel_file = request.files['excel']
        resume_file = request.files['resume']
        # Parse Excel and insert rows into MongoDB
        df = pandas.read_excel(excel_file)
        records = df.to_dict(orient='records')
        collection.delete_many({})
        collection.insert_many(records)
        # Encode resume as base64
        resume_bytes = resume_file.read()
        resume_b64 = base64.b64encode(resume_bytes).decode('utf-8')
        return jsonify({'resume_b64': resume_b64}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Endpoint to fetch job details from MongoDB
@app.route('/read_job_details', methods=['GET'])
def read_job_details():
    try:
        records = list(collection.find({}, {'_id': 0}))
        return jsonify(records), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/pepare_email", methods=["POST"])
def pepare_email():
    try:
        data = request.get_json()
        job_details = data['job_details']
        resume_b64 = data['resume_b64']
        # Replace NaN/None with empty string for Gemini API prompt
        def safe_str(val):
            if val is None:
                return ""
            try:
                import math
                if isinstance(val, float) and math.isnan(val):
                    return ""
            except:
                pass
            return str(val)

        name = safe_str(job_details[2])
        email_To = safe_str(job_details[1])
        company = safe_str(job_details[0])
        requirements = safe_str(job_details[3])
        # Decode resume and extract text
        resume_bytes = base64.b64decode(resume_b64)
        resume_text = ""
        pdf_file = BytesIO(resume_bytes)
        reader = PyPDF2.PdfReader(pdf_file)
        for page in reader.pages:
            resume_text += page.extract_text() + "\n"
        # Prompt
        prompt = f"""
        You are an expert email copywriter specializing in professional networking, referrals, and job outreach.
        find below details to prepare email
        - Name of the recipient (HR or employee):  {name} if name is nan/empty please use "Hiring Manager"
        - Company name: {company} if comapny is nan/empty please use "your company"
        - Recipient’s email: {email_To}
        - Job requirements (skills, experience, role details): {requirements} if Job requirements is nan/empty please use "Airflow, Python, SQL, Data Engineering, Openshift, AWS S3, ADLS, Docker, Kubernetes, OKTA, GITHUB Actions, CICD, ArgoCD, Tekton, Spark, ELT, ETL, Data Pipelines, SSIS, Tablueau, Kafka, Helm Charts, AI Agents, LLM's Agile, Scrum"
        - My resume text: {resume_text} 
    - Email subject line:
        * Professional, Polite, concise, and engaging.
        * Mention where I came across the opportunity or why I’m reaching out — only if actual information is available. 
            If not, omit the sentence completely without placeholders or suggestions.
        * Highlight 3–4 key points from my resume that match the job requirements.
        * Don't mention skills I don't know (based on the resume_text) as I know in the Email instead you can mention as I will learn them quickly.
        * Politely request a referral or to be considered for the role.
        * End with gratitude and willingness to share further details.
        * Add my contact numer 9618737291 and linkedIn profile link (https://www.linkedin.com/in/hiteshreddyp/) at the end in the signature
    4. Keep the tone professional yet approachable.
    5. Limit the email body to 220–350 words.
        * Any placeholder text like [mention…], (if known), or similar.
        * Any instructions, notes, or suggestions in the output.
    6. Use Markdown formatting for bullets (use * or - at the start of lines) and bold (**text**) for emphasis in the email body. Please use HTML tags (<strong> etc...) in the output instead.
    7. The entire output should be in html ready-to-send with no further edits required.
    8. At the end of the email body, append the following HTML tracking pixel (do not convert to Markdown, just add as HTML):
<img src="http://localhost:5002/track_view?email={email_To}" width="1" height="1" style="display:none;">

    Output format:
    Return ONLY valid JSON in the following format:
    {{
    "email_subject": "<subject line>",
    "email_body": "<email body>"
    }}


    """

        url = api_url
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        data = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ]
        }
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        # Post-process: convert Markdown bold (**) to <strong> and bullets to <ul><li>
        import re
        def markdown_to_html(text):
            # Convert **bold** to <strong>bold</strong>
            text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
            # Convert __bold__ to <strong>bold</strong>
            text = re.sub(r'__(.*?)__', r'<strong>\1</strong>', text)
            # Convert bullets (*, -, +) to <ul><li>...</li></ul>
            bullet_lines = re.findall(r'(^\s*([\*\-\+])\s+.*)', text, flags=re.MULTILINE)
            if bullet_lines:
                # Remove bullets from main text
                text_no_bullets = re.sub(r'^\s*([\*\-\+])\s+.*\n?', '', text, flags=re.MULTILINE)
                # Build HTML list
                items = [re.sub(r'^\s*([\*\-\+])\s+', '', line[0]).strip() for line in bullet_lines]
                ul_html = '<ul>' + ''.join([f'<li>{item}</li>' for item in items]) + '</ul>'
                text = text_no_bullets.strip() + '\n' + ul_html
            return text
        # If Gemini returns the expected JSON format
        if 'email_subject' in result and 'email_body' in result:
            result['email_subject'] = markdown_to_html(result['email_subject'])
            result['email_body'] = markdown_to_html(result['email_body'])
        return result
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/send_email", methods=["POST"])
def send_email():
    try:
        data = request.get_json()
        email_subject = data['email_subject']
        email_body = data['email_body']
        to_email = data['to_email']
        resume_b64 = data['resume_b64']
        from_email = data.get('from_email', 'hiteshreddy2181@gmail.com')
        smtp_user = os.getenv("SMTP_USER", "user")
        smtp_password = os.getenv("SMTP_PASSWORD", "password")
        msg = MIMEMultipart()
        msg['Subject'] = email_subject
        msg['From'] = from_email
        msg['To'] = to_email
        msg.attach(MIMEText(email_body, 'html'))
        resume_bytes = base64.b64decode(resume_b64)
        part = MIMEApplication(resume_bytes, Name="resume.pdf")
        part['Content-Disposition'] = 'attachment; filename=\"resume.pdf\"'
        msg.attach(part)
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_email, to_email, msg.as_string())
            server.quit()
            print(f"✅ Email sent to {to_email} with subject: {email_subject} and attachment: resume.pdf")
            return jsonify({"message": f"Email sent to {to_email}"}), 200
        except Exception as mail_err:
            return jsonify({"error": str(mail_err)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/agent', methods=['POST'])
def agent():
    try:
        data = request.get_json()
        resume_b64 = data['resume_b64']
        # 1. Call /read_job_details endpoint
        job_details_resp = requests.get("http://localhost:5001/read_job_details")
        if job_details_resp.status_code != 200:
            return jsonify({"error": job_details_resp.text}), 500
        job_details = pandas.DataFrame(job_details_resp.json())
        print("Job details read successfully.")
        print(f"Job Details: {job_details}")
        def safe_str(val):
            if val is None:
                return ""
            try:
                import math
                if isinstance(val, float) and math.isnan(val):
                    return ""
            except:
                pass
            return str(val)

        for idx, row in job_details.iterrows():
            print(row)
            # Sanitize all values in job_details row
            sanitized_row = [safe_str(val) for val in row.tolist()]
            # 2. Call /pepare_email endpoint
            email_resp = requests.post(
                "http://localhost:5001/pepare_email",
                json={"job_details": sanitized_row, "resume_b64": resume_b64}
            )
            if email_resp.status_code != 200:
                return jsonify({"error": "Failed to prepare email"}), 500
            email = email_resp.json()
            print("Email prepared successfully.")
            print(f"Email: {email}")
            text = email['candidates'][0]['content']['parts'][0]['text']
            # Remove code block markers if present
            if text.startswith("```json"):
                text = text.replace("```json", "").replace("```", "").strip()
            # Parse the JSON
            email_json = json.loads(text)
            email_subject = email_json.get("email_subject", "")
            email_body = email_json.get("email_body", "")
            print(f"Email Subject: {email_subject}")
            print(f"Email Body: {email_body}")
            #to_email = row[1] if row[1] else 'peddireddyhiteshreddy@gmail.com'
            to_email = 'peddireddyhiteshreddy@gmail.com'
            print(f"Sending email to: {to_email}")
            # 3. Call /send_email endpoint
            send_resp = requests.post(
                "http://localhost:5001/send_email",
                json={
                    "email_subject": email_subject,
                    "email_body": email_body,
                    "to_email": to_email,
                    "resume_b64": resume_b64
                }
            )
            if send_resp.status_code != 200:
                return jsonify({"error": "Failed to send email"}), 500
        return jsonify({"message": "Emails processed"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

