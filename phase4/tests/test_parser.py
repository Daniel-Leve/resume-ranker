"""
Tests for Phase 4 Job Description Parser and Keyword Extractor.
"""
from phase4.parser import extract_keywords_from_text, parse_job_requirements


def test_extract_keywords_from_text() -> None:
    text = "- 3+ years of professional Java development with Spring Boot and PostgreSQL"
    kws = extract_keywords_from_text(text)
    lower_kws = [k.lower() for k in kws]
    assert "java" in lower_kws
    assert "spring boot" in lower_kws or "spring" in lower_kws
    assert "postgresql" in lower_kws
    # Common stopwords should not be extracted
    assert "with" not in lower_kws
    assert "years" not in lower_kws
    assert "professional" not in lower_kws


def test_parse_structured_job_description() -> None:
    jd = """
    Senior Backend Engineer

    Required skills:
    - 5+ years of Java experience
    - Strong expertise in Spring Boot and Docker
    - Microservices architecture

    Nice to have:
    - Experience with Kafka or RabbitMQ
    - AWS cloud deployment (S3, ECS)

    Responsibilities:
    - Design and build RESTful APIs
    """
    reqs = parse_job_requirements(jd)
    assert len(reqs) >= 5

    categories = [r.category for r in reqs]
    assert "required" in categories
    assert "preferred" in categories
    assert "general" in categories

    req_texts = " ".join([r.text for r in reqs]).lower()
    assert "java" in req_texts
    assert "spring boot" in req_texts
    assert "kafka" in req_texts


def test_parse_unstructured_job_description() -> None:
    jd = "We are seeking a Python engineer with extensive FastAPI and MongoDB expertise to maintain backend services."
    reqs = parse_job_requirements(jd)
    assert len(reqs) >= 1
    assert reqs[0].category == "general"
    lower_kws = [k.lower() for k in reqs[0].keywords]
    assert "python" in lower_kws or "fastapi" in lower_kws


def test_parse_empty_job_description() -> None:
    assert parse_job_requirements("") == []
    assert parse_job_requirements("   \n\t  ") == []
