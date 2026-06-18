from __future__ import annotations

import fitz

from evals.golden.suite import (
    EvalChunk,
    evaluate_case,
    generate_fixture_files,
    load_golden_cases,
    summarize_results,
)


def test_evaluate_case_matches_expected_sources_pages_and_substrings() -> None:
    case = {
        "id": "schema_payment_flow",
        "query": "Что изображено на схеме оплаты?",
        "expected_source_ids": ["schema_pdf"],
        "expected_pages": [1],
        "expected_substrings": ["проверка оплаты", "нет оплаты"],
        "forbidden_source_ids": ["vim_text"],
    }
    chunks = [
        EvalChunk(
            source_id="schema_pdf",
            document_id="doc-schema",
            filename="golden_schema.pdf",
            content="Схема PAYMENT_FLOW_GOLDEN: проверка оплаты -> нет оплаты -> оплатить.",
            score=0.91,
            page=1,
        ),
        EvalChunk(
            source_id="linux_text",
            document_id="doc-linux",
            filename="golden_linux.txt",
            content="Linux navigation notes.",
            score=0.62,
        ),
    ]

    result = evaluate_case(case, chunks)

    assert result.passed is True
    assert result.found_source_ids == ["schema_pdf", "linux_text"]
    assert result.matched_substrings == ["проверка оплаты", "нет оплаты"]
    assert result.failures == []


def test_evaluate_case_reports_forbidden_source_and_missing_substring() -> None:
    case = {
        "id": "linux_pwd",
        "query": "Как узнать текущую директорию?",
        "expected_source_ids": ["linux_text"],
        "expected_substrings": ["pwd", "текущая директория"],
        "forbidden_source_ids": ["vim_text"],
    }
    chunks = [
        EvalChunk(
            source_id="vim_text",
            document_id="doc-vim",
            filename="golden_vim.txt",
            content="Vim visual mode uses v and V.",
            score=0.8,
        )
    ]

    result = evaluate_case(case, chunks)

    assert result.passed is False
    assert "missing expected source: linux_text" in result.failures
    assert "forbidden source retrieved: vim_text" in result.failures
    assert "missing expected substring: pwd" in result.failures


def test_evaluate_case_can_expect_no_results() -> None:
    case = {
        "id": "out_of_knowledge",
        "query": "ZXQ-77 methane forecast on Europa?",
        "expect_no_results": True,
    }

    empty_result = evaluate_case(case, [])
    noisy_result = evaluate_case(
        case,
        [
            EvalChunk(
                source_id="linux_text",
                document_id="doc-linux",
                filename="golden_linux.txt",
                content="Linux shell commands.",
                score=0.44,
            )
        ],
    )

    assert empty_result.passed is True
    assert noisy_result.passed is False
    assert noisy_result.failures == ["expected no retrieval results, got 1"]


def test_summarize_results_counts_passed_and_failed_cases() -> None:
    passed = evaluate_case({"id": "empty", "query": "nothing", "expect_no_results": True}, [])
    failed = evaluate_case(
        {"id": "missing", "query": "missing", "expected_source_ids": ["scan_pdf"]},
        [],
    )

    summary = summarize_results([passed, failed])

    assert summary == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "pass_rate": 0.5,
    }


def test_generate_fixture_files_creates_valid_documents(tmp_path) -> None:
    artifacts = generate_fixture_files(tmp_path)

    assert set(artifacts) == {
        "linux_text",
        "vim_text",
        "scan_pdf",
        "schema_pdf",
        "table_pdf",
        "url_image_page",
    }
    assert artifacts["linux_text"].path.read_text(encoding="utf-8").count("GOLDEN_LINUX_PWD") == 1
    assert "golden_url_image.png" in artifacts["url_image_page"].path.read_text(encoding="utf-8")

    with fitz.open(artifacts["scan_pdf"].path) as scan_doc:
        assert len(scan_doc) == 1
        assert scan_doc[0].get_text("text").strip() == ""

    with fitz.open(artifacts["table_pdf"].path) as table_doc:
        assert "GOLDEN_TABLE_PLAN" in table_doc[0].get_text("text")


def test_load_golden_cases_has_unique_required_cases() -> None:
    cases = load_golden_cases()
    case_ids = [case["id"] for case in cases]

    assert len(case_ids) == len(set(case_ids))
    assert {
        "linux_command_navigation",
        "vim_visual_mode",
        "scan_ru_ocr",
        "schema_payment_flow",
        "table_tariff_values",
        "url_image_router_action",
        "out_of_knowledge",
    }.issubset(case_ids)
