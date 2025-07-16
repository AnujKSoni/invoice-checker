import re
import os
import csv
import pdfplumber
import pytesseract
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from io import StringIO
from PIL import Image
from pathlib import Path
from datetime import datetime
from pymongo import MongoClient
from transformers import pipeline
from dotenv import load_dotenv

# Page config & hide default Streamlit UI
st.set_page_config(page_title="Compliance Suite", page_icon="📑", layout="wide")
st.markdown("""
<style>
#MainMenu, header, footer {visibility: hidden;}
.stApp > header, .stApp > footer {display: none;}
</style>
""", unsafe_allow_html=True)

# Load and inject frontend shell
try:
    base = Path(__file__).parent / "components" / "frontend"
    html = (base / "index.html").read_text()
    css = (base / "styles.css").read_text()
    js = (base / "scripts.js").read_text()
    
    # Inject the shell with a small height so it doesn't interfere
    components.html(f"<style>{css}</style>{html}<script>{js}</script>", height=100, scrolling=False)
except:
    st.error("Frontend files not found. Please check the components/frontend folder.")

# MongoDB setup
load_dotenv()
mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)
db = client["invoice_checker"]
collection = db["analyses"]

# Q&A pipeline
@st.cache_resource
def get_qa_pipeline():
    return pipeline("question-answering", model="distilbert-base-cased-distilled-squad")

qa_pipeline = get_qa_pipeline()

def ask_local_qa(question, context):
    if not question or not context:
        return ""
    result = qa_pipeline(question=question, context=context[:2000])
    return result.get("answer", "")

# Parsing functions (keep your original logic)
def parse_gstin(text):
    patterns = [
        r'GSTIN\s*[:\-]?\s*([A-Z0-9]{13,16})',
        r'GST\s*Number\s*[:\-]?\s*([A-Z0-9]{13,16})',
        r'GST\s*IN\s*[:\-]?\s*([A-Z0-9]{13,16})',
        r'([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z])'
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            candidate = match.group(1)
            if len(candidate) == 15:
                return candidate
    return None

def parse_invoice_no(text):
    patterns = [
        r'Invoice\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Za-z0-9\-\/]+)',
        r'Chalan\s*No\s*[:\-]?\s*([A-Za-z0-9\-\/]+)',
        r'PO\.?\s*No\s*[:\-]?\s*([A-Za-z0-9\-\/]+)',
        r'No\s*[:\-]?\s*([A-Za-z0-9\-\/]+)',
        r'([A-Za-z0-9]{6,})'
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def parse_total_amount(text):
    patterns = [
        r'Total\s*Amount\s*[:\-]?\s*([\d,]+\.\d{2})',
        r'Total\s*[:\-]?\s*([\d,]+\.\d{2})',
        r'[₹Rs\.]?\s*([\d,]+\.\d{2})'
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def parse_audit_report_fields(text):
    organization_name = None
    audit_period = None
    auditor_name = None
    opinion = None
    report_date = None
    total_income = None
    total_expenses = None
    net_worth = None
    auditor_comments = None

    org_match = re.search(r'^\s*([A-Za-z &\(\)\.\-]+)\s*\n.*AUDIT REPORT', text, re.DOTALL | re.IGNORECASE)
    if org_match:
        organization_name = org_match.group(1).strip()

    period_match = re.search(r'For the Period\s*([A-Za-z0-9\s\-\/]+)', text, re.IGNORECASE)
    if period_match:
        audit_period = period_match.group(1).strip()

    auditor_match = re.search(r'PRINT NAME & SIGNATURE\s*\n*(.*\n)?\s*Auditor', text, re.IGNORECASE)
    if auditor_match:
        auditor_name = auditor_match.group(1).strip() if auditor_match.group(1) else ""

    opinion_match = re.search(
        r'In my opinion[^\n]*,?\s*(.*?)(?=\n\s*\n|\n[A-Z][A-Z ]+\n)',
        text, re.IGNORECASE | re.DOTALL)
    if opinion_match:
        opinion = opinion_match.group(1).replace('\n', ' ').strip()

    date_match = re.search(r'(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})', text)
    if date_match:
        report_date = date_match.group(1)

    income_match = re.search(r'TOTAL INCOME\s*\$([\d,\.]+)', text, re.IGNORECASE)
    if income_match:
        total_income = income_match.group(1).strip()

    expense_match = re.search(r'TOTAL EXPENSE[S]?\s*\$([\d,\.]+)', text, re.IGNORECASE)
    if expense_match:
        total_expenses = expense_match.group(1).strip()

    net_worth_match = re.search(r'NET WORTH[^\$]*\$([\d,\.]+)', text, re.IGNORECASE)
    if net_worth_match:
        net_worth = net_worth_match.group(1).strip()

    comments_match = re.search(r'AUDITOR COMMENTS?[\s\:]*([\s\S]{0,300}?)\n\n', text, re.IGNORECASE)
    if comments_match:
        auditor_comments = comments_match.group(1).strip()
    
    return {
        "organization_name": organization_name or "",
        "audit_period": audit_period or "",
        "auditor_name": auditor_name or "",
        "opinion": opinion or "",
        "report_date": report_date or "",
        "total_income": total_income or "",
        "total_expenses": total_expenses or "",
        "net_worth": net_worth or "",
        "auditor_comments": auditor_comments or ""
    }

def extract_text(uploaded_file):
    uploaded_file.seek(0)
    if uploaded_file.type == "application/pdf":
        with pdfplumber.open(uploaded_file) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text
    else:
        image = Image.open(uploaded_file)
        return pytesseract.image_to_string(image)

def extract_all_tables(uploaded_file):
    tables = []
    if uploaded_file.type == "application/pdf":
        uploaded_file.seek(0)
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                page_tables = page.extract_tables()
                for table in page_tables:
                    if table and len(table) > 1:
                        df = pd.DataFrame(table)
                        if df.dropna(how='all').shape[0] > 1:
                            df.columns = df.iloc[0]
                            df = df[1:].reset_index(drop=True)
                            tables.append(df)
    return tables

def validate_gstin(gstin):
    if not gstin or len(gstin) != 15:
        return False
    return bool(re.match(r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]', gstin))

def check_gst_invoice_compliance(parsed_data):
    issues = []
    if not parsed_data.get('gstin'):
        issues.append("GSTIN not found")
    elif not validate_gstin(parsed_data.get('gstin')):
        issues.append("Invalid GSTIN format")
    if not parsed_data.get('invoice_no'):
        issues.append("Invoice number missing")
    if not parsed_data.get('total_amount'):
        issues.append("Total amount missing")
    return {
        'status': 'COMPLIANT' if not issues else 'NON_COMPLIANT',
        'issues': issues
    }

def check_audit_report_compliance(fields):
    issues = []
    if not fields.get("opinion"):
        issues.append("Audit opinion not found")
    if not fields.get("auditor_name"):
        issues.append("Auditor name missing")
    if not fields.get("total_income"):
        issues.append("Total income missing")
    if not fields.get("total_expenses"):
        issues.append("Total expenses missing")
    if not fields.get("net_worth"):
        issues.append("Net worth missing")
    if not fields.get("organization_name"):
        issues.append("Organization name missing")
    if not fields.get("audit_period"):
        issues.append("Audit period missing")
    return {
        "status": "COMPLIANT" if not issues else "NON_COMPLIANT",
        "issues": issues
    }

def save_analysis(parsed_data, compliance, filename, doc_type):
    document = {
        'filename': filename,
        'doc_type': doc_type,
        **parsed_data,
        'compliance_status': compliance['status'],
        'issues': compliance['issues'],
        'timestamp': datetime.now()
    }
    result = collection.insert_one(document)
    return str(result.inserted_id)

def parse_fields(text, doc_type):
    if doc_type == "GST Invoice":
        return {
            'gstin': parse_gstin(text),
            'invoice_no': parse_invoice_no(text),
            'total_amount': parse_total_amount(text)
        }
    elif doc_type == "Audit Report":
        return parse_audit_report_fields(text)
    else:
        st.warning(f"Parsing for '{doc_type}' not yet implemented.")
        return {}

def check_compliance(parsed_data, doc_type):
    if doc_type == "GST Invoice":
        return check_gst_invoice_compliance(parsed_data)
    elif doc_type == "Audit Report":
        return check_audit_report_compliance(parsed_data)
    else:
        return {'status': 'UNSUPPORTED', 'issues': ['Compliance rules not implemented yet.']}

def generate_report_csv(filename, doc_type, reviewed_data, compliance):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Compliance Report"])
    writer.writerow(["File Name", filename])
    writer.writerow(["Document Type", doc_type])
    writer.writerow(["Timestamp", datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow([])
    writer.writerow(["Field", "Value"])
    for k, v in reviewed_data.items():
        writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["Compliance Status", compliance['status']])
    writer.writerow(["Issues"])
    if compliance['issues']:
        for issue in compliance['issues']:
            writer.writerow(["", issue])
    else:
        writer.writerow(["", "None"])
    return output.getvalue()

def get_csv_download_of_tables(tables):
    if tables:
        output = StringIO()
        tables[0].to_csv(output, index=False)
        return output.getvalue()
    return None

def main():
    doc_type = st.selectbox(
        "Select Document Type",
        ["GST Invoice", "Audit Report", "Legal Contract (Coming Soon)", "Regulatory Filing (Coming Soon)"]
    )

    uploaded_file = st.file_uploader(
        f"Upload your {doc_type}",
        type=['pdf', 'jpg', 'jpeg', 'png'],
        help="Supports PDF and image formats"
    )

    tables = None

    if uploaded_file:
        st.success("✅ File uploaded successfully")

        st.write("### File Details")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"📄 **File Name:** {uploaded_file.name}")
            st.write(f"📂 **Size:** {uploaded_file.size:,} bytes")
        with col2:
            st.write(f"📁 **Type:** {uploaded_file.type}")
            if uploaded_file.type.startswith('image/'):
                st.image(uploaded_file, caption="Preview", use_column_width=True)

        st.write("### Step 1: Raw Text Extraction")
        with st.spinner("🔍 Extracting text..."):
            extracted_text = extract_text(uploaded_file)
        st.text_area("Extracted Text", extracted_text, height=200)

        st.subheader("Ask Your Document (Local AI-Powered)")
        question = st.text_input("Ask a question about this document (e.g., 'What is the invoice number?' or 'Who is the auditor?')")
        if question and extracted_text.strip():
            with st.spinner("AI is reading your document..."):
                answer = ask_local_qa(question, extracted_text)
            st.write(f"**Answer:** {answer}")

        if doc_type == "GST Invoice" and uploaded_file.type == 'application/pdf':
            tables = extract_all_tables(uploaded_file)
            if tables:
                st.write("### Step 1B: Detected Invoice Table(s)")
                for idx, table in enumerate(tables):
                    st.write(f"**Table {idx+1}:**")
                    st.dataframe(table)
                csv_data = get_csv_download_of_tables(tables)
                if csv_data:
                    st.download_button(
                        label="Download First Table as CSV",
                        data=csv_data,
                        file_name=f"{uploaded_file.name}_lineitems.csv",
                        mime="text/csv"
                    )

        st.write("### Step 2: Field Extraction & Editable Review")
        parsed_data = parse_fields(extracted_text, doc_type)

        with st.form("review_fields"):
            reviewed_data = {}

            if doc_type == "GST Invoice":
                gstin = st.text_input("GSTIN", value=parsed_data.get("gstin", ""))
                invoice_no = st.text_input("Invoice Number", value=parsed_data.get("invoice_no", ""))
                total_amount = st.text_input("Total Amount", value=parsed_data.get("total_amount", ""))
                run_check = st.form_submit_button("Run Compliance Check")
                reviewed_data = {
                    "gstin": gstin.strip(),
                    "invoice_no": invoice_no.strip(),
                    "total_amount": total_amount.strip()
                }

            elif doc_type == "Audit Report":
                organization_name = st.text_input("Organization Name", value=parsed_data.get("organization_name", ""))
                audit_period = st.text_input("Audit Period", value=parsed_data.get("audit_period", ""))
                auditor_name = st.text_input("Auditor Name", value=parsed_data.get("auditor_name", ""))
                opinion = st.text_area("Audit Opinion", value=parsed_data.get("opinion", ""))
                report_date = st.text_input("Report Date", value=parsed_data.get("report_date", ""))
                total_income = st.text_input("Total Income", value=parsed_data.get("total_income", ""))
                total_expenses = st.text_input("Total Expenses", value=parsed_data.get("total_expenses", ""))
                net_worth = st.text_input("Net Worth", value=parsed_data.get("net_worth", ""))
                auditor_comments = st.text_area("Auditor Comments", value=parsed_data.get("auditor_comments", ""))
                run_check = st.form_submit_button("Run Compliance Check")
                reviewed_data = {
                    "organization_name": organization_name.strip() if organization_name else "",
                    "audit_period": audit_period.strip() if audit_period else "",
                    "auditor_name": auditor_name.strip() if auditor_name else "",
                    "opinion": opinion.strip() if opinion else "",
                    "report_date": report_date.strip() if report_date else "",
                    "total_income": total_income.strip() if total_income else "",
                    "total_expenses": total_expenses.strip() if total_expenses else "",
                    "net_worth": net_worth.strip() if net_worth else "",
                    "auditor_comments": auditor_comments.strip() if auditor_comments else ""
                }
            else:
                st.write("No editable fields available yet for this document type.")
                run_check = False

            if run_check:
                st.session_state['reviewed_data'] = reviewed_data
                st.session_state['compliance'] = check_compliance(st.session_state['reviewed_data'], doc_type)

        if 'compliance' in st.session_state and 'reviewed_data' in st.session_state:
            compliance = st.session_state['compliance']
            reviewed_data = st.session_state['reviewed_data']

            st.write("### Step 3: Compliance Check")
            if compliance['status'] != 'UNSUPPORTED':
                if st.button("Save to Database"):
                    doc_id = save_analysis(reviewed_data, compliance, uploaded_file.name, doc_type)
                    st.success(f"✅ Analysis saved! ID: {doc_id}")
                    del st.session_state['compliance']
                    del st.session_state['reviewed_data']

                report_csv = generate_report_csv(uploaded_file.name, doc_type, reviewed_data, compliance)
                st.download_button(
                    label="Download Compliance Report (CSV)",
                    data=report_csv,
                    file_name=f"{uploaded_file.name}_compliance_report.csv",
                    mime="text/csv"
                )
                
                if compliance['status'] == 'COMPLIANT':
                    st.markdown("""
                    <div class="metric-card success-card">
                        <h3>✅ Document is COMPLIANT</h3>
                        <p>All required fields are present and valid</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown("""
                    <div class="metric-card error-card">
                        <h3>❌ Document is NON-COMPLIANT</h3>
                        <p>Issues found - please review below</p>
                    </div>
                    """, unsafe_allow_html=True)
                    for issue in compliance['issues']:
                        st.write(f"- {issue}")

    st.sidebar.title("📊 Recent Analyses")
    if st.sidebar.button("Show Latest"):
        recent = list(collection.find().sort("timestamp", -1).limit(5))
        for doc in recent:
            st.sidebar.markdown(f"**{doc['filename']}**")
            st.sidebar.write(f"• Type: {doc['doc_type']}")
            st.sidebar.write(f"• Status: `{doc['compliance_status']}`")
            st.sidebar.markdown("---")

if __name__ == "__main__":
    main()
