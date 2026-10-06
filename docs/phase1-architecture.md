# Phase 1 Architecture — Asynchronous PDF Resume Text Extraction

## 1. What is Phase 1 Doing? (In Simple Terms)

PDF resumes are difficult for computers and AI search engines to read directly. They contain complex formatting, multi-column layouts, tables, and images.

**Phase 1 has one single responsibility:**
> Take an uploaded PDF resume, read every single character out of it using AWS's OCR engine (**Amazon Textract**), and output a clean, standardized **JSON file** containing the full text and page layout.

Phase 1 does **not** do chunking, does **not** generate vector embeddings, and does **not** rank candidates. It simply turns a raw `.pdf` file into structured `.json` text.

---

## 2. Visual Architecture & Flowchart

Here is the complete step-by-step flow of how a resume travels through AWS in Phase 1:

```
[ Candidate / Recruiter / API ]
               │
               │  Uploads PDF
               ▼
┌────────────────────────────────────────────────────────┐
│ Amazon S3 Bucket: ai-resume-screening-dev...           │
│ Folder: incoming/resume.pdf                            │
└───────────────────────┬────────────────────────────────┘
                        │
                        │ S3 Event (ObjectCreated)
                        ▼
┌────────────────────────────────────────────────────────┐
│ AWS Lambda: resume-start-textract                      │
│ - Verifies folder is "incoming/" and file is ".pdf"    │
│ - Calls Textract API (StartDocumentTextDetection)      │
│ - Shuts down immediately (Execution time: ~0.5s)       │
└───────────────────────┬────────────────────────────────┘
                        │
                        │ Hands off PDF to Textract
                        ▼
┌────────────────────────────────────────────────────────┐
│ Amazon Textract (Asynchronous OCR Engine)              │
│ - Reads text, lines, words, and pages in background   │
│ - Takes 10 to 60 seconds depending on page count       │
└───────────────────────┬────────────────────────────────┘
                        │
                        │ Job Finished! (Success / Failure)
                        ▼
┌────────────────────────────────────────────────────────┐
│ Amazon SNS Topic: resume-textract-completed            │
│ - Broadcasts notification: "Job ID 12345 is ready!"   │
└───────────────────────┬────────────────────────────────┘
                        │
                        │ Triggers subscriber
                        ▼
┌────────────────────────────────────────────────────────┐
│ AWS Lambda: resume-collect-textract                    │
│ - Reads the SNS notification                           │
│ - Calls Textract API (GetDocumentTextDetection)        │
│ - Paginates through all pages                          │
│ - Stitches raw lines into clean full text              │
└───────────────────────┬────────────────────────────────┘
                        │
                        │ Writes structured JSON
                        ▼
┌────────────────────────────────────────────────────────┐
│ Amazon S3 Bucket: ai-resume-screening-dev...           │
│                                                        │
│ [ If Successful ] ──> extracted/<textract-job-id>.json │
│ [ If Failed ]     ──> failed/<textract-job-id>.json    │
└────────────────────────────────────────────────────────┘
                        │
                        ▼
           Ready for Phase 2 Indexing!
```

---

## 3. Step-by-Step Data Journey

### Step 1: The PDF Lands in S3
* A resume is uploaded to `s3://<bucket>/incoming/<filename>.pdf`.
* In our SaaS setup, the filename carries tenant and job IDs:  
  `incoming/saas__<tenant_id>__<job_id>__<application_id>.pdf`.

### Step 2: S3 Wakes Up the "Start" Lambda
* S3 has an automatic trigger configured. The moment an object is created under `incoming/*.pdf`, S3 fires an event to **`resume-start-textract`**.
* The Lambda checks:
  1. Is the file in the `incoming/` folder? (Yes)
  2. Does the filename end with `.pdf`? (Yes)
* If valid, it calls `textract.start_document_text_detection(...)` and attaches:
  - The S3 location of the PDF.
  - The Amazon SNS Topic ARN to notify upon completion.
  - The IAM Role allowing Textract to talk to SNS.
* **The Lambda exits immediately.** It does *not* wait for Textract to finish.

### Step 3: Textract Reads the Document Asynchronously
* Amazon Textract opens the PDF in the cloud.
* It scans every page, detects handwriting and printed text, figures out reading order, and bundles everything into blocks (PAGE, LINE, WORD).
* This background process takes anywhere from 10 to 45 seconds.

### Step 4: Textract Alerts SNS
* When OCR finishes, Textract automatically publishes a message to the **`resume-textract-completed`** SNS Topic:
  ```json
  {
    "JobId": "18e12c6530ee3a69b...",
    "Status": "SUCCEEDED",
    "DocumentLocation": {
      "S3Bucket": "ai-resume-screening-dev-761595200930",
      "S3ObjectName": "incoming/saas__...pdf"
    }
  }
  ```

### Step 5: The "Collect" Lambda Downloads and Assembles Text
* The SNS Topic immediately triggers the second Lambda: **`resume-collect-textract`**.
* The Collect Lambda:
  1. Grabs the `JobId` from the notification.
  2. Calls `textract.get_document_text_detection(JobId=...)`.
  3. Uses a `while (NextToken)` pagination loop to retrieve all pages without missing any text.
  4. Pulls out every line with `BlockType == 'LINE'` and joins them with `\n` to produce clean, readable resume text.

### Step 6: Storing the Extracted Result
* The Collect Lambda writes the final JSON to S3:
  `s3://<bucket>/extracted/<textract-job-id>.json`.
* If Textract failed (e.g. password-protected or corrupt PDF), it writes an error log to:
  `s3://<bucket>/failed/<textract-job-id>.json`.

---

## 4. The Core AWS Components Explained

| AWS Resource | Real-World Role | Why We Use It |
|---|---|---|
| **Amazon S3** | The Filing Cabinet | Stores PDFs and output JSON files privately and durably with AES-256 encryption. |
| **`resume-start-textract` (Lambda)** | The Dispatcher | Wakes up instantly on upload, starts the Textract job, and shuts down in under 500ms. |
| **Amazon Textract** | The OCR Engine | AWS AI service that accurately extracts text and layout from multi-page PDFs. |
| **`resume-textract-completed` (SNS)** | The Pager / Bell | Alerts our system the exact second Textract finishes processing. |
| **`resume-collect-textract` (Lambda)** | The Scribe | Gathers the OCR text from Textract, formats it cleanly, and stores it into S3. |

---

## 5. Why Two Lambdas Instead of One? (The Cost Trick)

You might wonder: *Why not have one Lambda that uploads the file, waits for Textract, and saves the JSON?*

**The Problem with One Lambda:**
* Textract OCR takes 15 to 60 seconds to read a PDF.
* AWS Lambda charges you for every millisecond it stays alive. If a Lambda just sits there waiting for Textract, **you are paying for dead, idle time**.
* If a 20-page resume takes 2 minutes, a waiting Lambda might hit a timeout and fail.

**The Solution with Two Lambdas (Decoupled Pattern):**
1. **Lambda 1 (`start`)** runs for **0.4 seconds** and stops. (Cost: virtually \$0.000001).
2. **Textract** runs in AWS's own background fleet.
3. **SNS** rings the bell when finished.
4. **Lambda 2 (`collect`)** wakes up, downloads results in **1.2 seconds**, and stops.
* **Total paid Lambda duration:** Under 2 seconds instead of 60 seconds! This keeps the pipeline well within the \$100 AWS credit budget.

---

## 6. What Does the Output JSON Look Like?

When Phase 1 finishes, it drops a file at `s3://<bucket>/extracted/<job_id>.json`. Here is what is inside:

```json
{
  "job_id": "18e12c6530ee3a69b386ecbaa37b8b4ebbe51780c1564887b73544a4a40b64b2",
  "status": "SUCCEEDED",
  "source": {
    "bucket": "ai-resume-screening-dev-761595200930",
    "key": "incoming/saas__tenant1__job101__candidate99.pdf"
  },
  "page_count": 2,
  "text": "DANIEL LEVE\nBackend Software Engineer\nSummary\nExperienced Python and AWS developer...\nSkills\nPython, Docker, MongoDB...\nExperience\nSoftware Engineer at...",
  "blocks": [
    {
      "BlockType": "PAGE",
      "Id": "page-1",
      "Geometry": { ... }
    },
    {
      "BlockType": "LINE",
      "Id": "line-1",
      "Text": "DANIEL LEVE",
      "Confidence": 99.8
    }
  ],
  "metadata": {
    "processed_at": "2026-10-03T18:52:02+00:00",
    "pipeline_version": "phase1-v1"
  }
}
```

* **`source.key`**: Keeps track of the original PDF path and encoded multi-tenant IDs.
* **`text`**: The clean string ready for NLP section parsing and chunking in Phase 2.
* **`blocks`**: Detailed geometry and line-by-line confidence scores.

---

## 7. Error Handling & Edge Cases

* **Wrong File Type or Folder:**  
  If a recruiter uploads a `.docx`, `.png`, or uploads outside `incoming/`, `resume-start-textract` logs `Rejected non-Phase-1 S3 event` and stops. S3 will not trigger Textract.
* **Corrupt / Encrypted PDFs:**  
  If Textract encounters an unreadable or password-protected PDF, it sends a `FAILED` status to SNS. `resume-collect-textract` detects this and writes a clean error record to `s3://<bucket>/failed/<job_id>.json` so engineers can see what happened.
* **Large Resumes (Pagination):**  
  Textract caps response payloads at a few pages per API call. The collector Lambda uses `NextToken` pagination so 5, 10, or 25-page resumes are read completely without truncation.

---

## 8. Handoff to Phase 2

Once `extracted/<job_id>.json` is written to S3, Phase 1's work is complete.

* S3 triggers an event to our **`resume-indexing-dev` SQS Queue**.
* The **Phase 2 `IndexingWorker`** wakes up, reads the clean `text`, parses the sections (Skills, Experience, Education), generates **Voyage AI** vector embeddings, and stores them in **MongoDB Atlas** for candidate screening!
