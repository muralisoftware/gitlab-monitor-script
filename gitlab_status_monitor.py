import os, subprocess, smtplib, logging, traceback, configparser
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime, timedelta

# Logging
logging.basicConfig(format='(%(levelname)s) [%(asctime)s] %(message)s')
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)

# Load configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "gitlab-browse-sample.conf")
config = configparser.ConfigParser()
config.read(CONFIG_PATH)

EMAIL_TO = [e.strip() for e in config.get("EMAIL", "EMAIL_TO").strip("[]").split(",") if e.strip()]
EMAIL_CC = [e.strip() for e in config.get("EMAIL", "EMAIL_CC").strip("[]").split(",") if e.strip()]
EMAIL_FROM = config.get("EMAIL", "EMAIL_FROM").strip()
EMAIL_PASS = config.get("EMAIL", "EMAIL_PASS").strip()
SMTP_SERVER = config.get("EMAIL", "SMTP_SERVER").strip()
SMTP_PORT = config.getint("EMAIL", "SMTP_PORT")
EMAIL_SUBJECT = config.get("EMAIL", "EMAIL_SUBJECT").strip("[]")

# File paths
STATUS_FILE = "/tmp/gitlab_service_status.cache"
LAST_EMAIL_FILE = "/tmp/gitlab_last_email_sent.cache"

# Testing mode
USE_SAMPLE_OUTPUT = True
SAMPLE_OUTPUT = """
run: nginx: (pid 972) 7s; run: log: (pid 971) 7s
run: postgresql: (pid 962) 7s; run: log: (pid 959) 7s
run: redis: (pid 964) 7s; run: log: (pid 963) 7s
failed: sidekiq: (pid 967) 7s; run: log: (pid 966) 7s
run: puma: (pid 961) 7s; run: log: (pid 960) 7s
"""

# Load previous service status
if not os.path.exists(STATUS_FILE):
    open(STATUS_FILE, "w").close()

previous_status = {}
with open(STATUS_FILE, "r") as f:
    for line in f:
        if ':' in line:
            service, status = line.strip().split(":", 1)
            previous_status[service] = status

# Read last email time
last_email_sent = None
if os.path.exists(LAST_EMAIL_FILE):
    with open(LAST_EMAIL_FILE, "r") as f:
        try:
            last_email_sent = datetime.strptime(f.read().strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            last_email_sent = None

# Get status
LOGGER.info('Checking GitLab status...')
if USE_SAMPLE_OUTPUT:
    output = SAMPLE_OUTPUT.strip()
else:
    try:
        result = subprocess.run("gitlab-ctl status", shell=True, text=True, capture_output=True)
        output = result.stdout
    except subprocess.CalledProcessError:
        LOGGER.error("Error fetching GitLab status:\n" + traceback.format_exc())
        exit(1)

# Parse status
LOGGER.info('Processing GitLab status...')
new_status = {}
failed_services = []
for line in output.splitlines():
    line = line.strip()
    if not line:
        continue
    service_name = line.split(":")[1].strip()
    status = "failed" if not line.startswith("run:") else "running"
    new_status[service_name] = status
    if status == "failed":
        failed_services.append(service_name)

# Email condition
send_email = False
if failed_services:
    if not last_email_sent or datetime.now() - last_email_sent > timedelta(hours=1):
        send_email = True
        LOGGER.info("Failed services:\n" + ", ".join(failed_services))

# Compose and send email
if send_email:
    LOGGER.info('Sending email...')
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = f"The following GitLab services are DOWN as of {timestamp}:\n\n"
    body += "\n".join(f"- {svc}" for svc in failed_services)
    body += "\n\nPlease check the GitLab server."

    msg = MIMEText(body)
    msg["Subject"] = EMAIL_SUBJECT
    msg["From"] = formataddr(("GitLab Monitor", EMAIL_FROM))
    msg["To"] = ", ".join(EMAIL_TO)
    msg["Cc"] = ", ".join(EMAIL_CC)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASS)
            server.sendmail(EMAIL_FROM, EMAIL_TO + EMAIL_CC, msg.as_string())

        LOGGER.info('Email sent.')
        with open(LAST_EMAIL_FILE, "w") as f:
            f.write(timestamp)
    except Exception:
        LOGGER.error("Failed to send email:\n" + traceback.format_exc())
else:
    if failed_services:
        LOGGER.warning("Email was already sent within the last hour.")
    else:
        LOGGER.info("All services are running.")

# Save current service status
with open(STATUS_FILE, "w") as f:
    for svc, stat in new_status.items():
        f.write(f"{svc}:{stat}\n")
