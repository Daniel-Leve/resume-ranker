from pathlib import Path
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

output = Path('output/pdf/sample-resume.pdf')
output.parent.mkdir(parents=True, exist_ok=True)

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='Name', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=22,
                          leading=26, textColor=HexColor('#1f2937'), spaceAfter=4))
styles.add(ParagraphStyle(name='Contact', parent=styles['Normal'], fontSize=10, leading=14,
                          textColor=HexColor('#4b5563'), spaceAfter=16))
styles.add(ParagraphStyle(name='Section', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11,
                          leading=15, textColor=HexColor('#0f766e'), spaceBefore=12, spaceAfter=5))
styles.add(ParagraphStyle(name='Body', parent=styles['Normal'], fontSize=10, leading=14, textColor=HexColor('#1f2937')))

story = [
    Paragraph('Sample Candidate', styles['Name']),
    Paragraph('sample.candidate@example.test | +00 00000 00000 | Mumbai, India', styles['Contact']),
    HRFlowable(width='100%', thickness=0.8, color=HexColor('#d1d5db')), Spacer(1, 6),
    Paragraph('PROFILE', styles['Section']),
    Paragraph('Synthetic resume created solely to test the Phase 1 document-ingestion pipeline. It contains no real personal information.', styles['Body']),
    Paragraph('SKILLS', styles['Section']),
    Paragraph('Python, AWS, Amazon S3, AWS Lambda, REST APIs, SQL', styles['Body']),
    Paragraph('EXPERIENCE', styles['Section']),
    Paragraph('<b>Junior Software Engineer - Example Systems</b><br/>2024 - Present<br/>Built small automation services and maintained API integrations.', styles['Body']),
    Paragraph('EDUCATION', styles['Section']),
    Paragraph('<b>B.E., Computer Science</b><br/>Example Institute, 2024', styles['Body']),
]
SimpleDocTemplate(str(output), pagesize=A4, rightMargin=0.75*inch, leftMargin=0.75*inch,
                  topMargin=0.7*inch, bottomMargin=0.7*inch).build(story)
print(output)
