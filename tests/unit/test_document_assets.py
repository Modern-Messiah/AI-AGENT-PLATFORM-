from pathlib import Path

from packages.storage import Document, DocumentAsset


def test_document_tracks_visual_ingestion_progress() -> None:
    columns = Document.__table__.columns

    assert columns["processing_stage"].nullable is False
    assert columns["processed_pages"].nullable is False
    assert columns["total_pages"].nullable is False
    assert columns["warnings"].nullable is False


def test_document_asset_stores_ocr_and_preview_metadata() -> None:
    columns = DocumentAsset.__table__.columns

    assert columns["tenant_id"].nullable is False
    assert columns["document_id"].foreign_keys
    assert columns["preview_object_key"].nullable is False
    assert columns["page_number"].nullable is True
    assert columns["asset_kind"].nullable is False
    assert columns["ocr_text"].nullable is False
    assert columns["ocr_confidence"].nullable is True
    assert columns["vision_description"].nullable is False
    assert columns["width"].nullable is False
    assert columns["height"].nullable is False
    assert columns["status"].nullable is False


def test_document_assets_are_deleted_with_the_document() -> None:
    assert Document.assets.property.cascade.delete_orphan


def test_visual_assets_migration_enables_tenant_rls() -> None:
    migration = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "0010_document_assets.py"
    ).read_text()

    assert 'down_revision: str | None = "0009_notebook_insights"' in migration
    assert "CREATE TABLE document_assets" in migration
    assert "ON DELETE CASCADE" in migration
    assert "ix_document_assets_tenant_document" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY tenant_isolation ON document_assets" in migration
