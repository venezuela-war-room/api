import pytest
from pydantic import ValidationError

from app.schemas import PersonBulkCreate, PersonCreate, SearchParams


def test_person_create_valid_full():
    p = PersonCreate(
        full_name="Álvarez Maikeli",
        document_id="300454425",
        age=30,
        ubicacion_actual="Hosp. José Gregorio Hernández",
        tipo_instalacion="hospital",
        ubicacion_detalles="Registro hospitalario",
        lugar_procedencia="La Guaira",
        relevant_info="Politraumatismo",
        source_url="https://example.com/source",
        status="verified",
        fallecido=False,
    )
    assert p.full_name == "Álvarez Maikeli"
    assert p.document_id == "300454425"
    assert p.tipo_instalacion == "hospital"
    assert p.fallecido is False


def test_person_create_only_full_name():
    p = PersonCreate(full_name="Rosa Alvarez")
    assert p.full_name == "Rosa Alvarez"
    assert p.document_id is None
    assert p.ubicacion_actual is None
    assert p.status == "verified"
    assert p.fallecido is False


def test_person_create_strips_whitespace():
    p = PersonCreate(full_name="  Juan   Pérez  ")
    assert p.full_name == "Juan Pérez"


def test_person_create_full_name_too_short():
    with pytest.raises(ValidationError):
        PersonCreate(full_name="A")


def test_person_create_full_name_too_long():
    with pytest.raises(ValidationError):
        PersonCreate(full_name="A" * 201)


def test_person_create_document_id_normalizes_to_digits():
    p = PersonCreate(full_name="Test Person", document_id="V-12.345.678")
    assert p.document_id == "12345678"


def test_person_create_document_id_no_digits_raises():
    with pytest.raises(ValidationError):
        PersonCreate(full_name="Test Person", document_id="no-digits-here")


def test_person_create_invalid_status():
    with pytest.raises(ValidationError):
        PersonCreate(full_name="Test Person", status="dead")


def test_person_create_age_out_of_range():
    with pytest.raises(ValidationError):
        PersonCreate(full_name="Test Person", age=200)


def test_person_create_invalid_tipo_instalacion():
    with pytest.raises(ValidationError):
        PersonCreate(full_name="Test Person", tipo_instalacion="clinica_random")


def test_person_create_valid_tipos():
    for tipo in ("hospital", "albergue", "morgue", "punto_concentracion", "centro_medico"):
        p = PersonCreate(full_name="Test Person", tipo_instalacion=tipo)
        assert p.tipo_instalacion == tipo


def test_person_create_fallecido_flag():
    p = PersonCreate(full_name="Test Person", fallecido=True)
    assert p.fallecido is True


def test_bulk_create_valid():
    bulk = PersonBulkCreate(people=[PersonCreate(full_name="Ana García"), PersonCreate(full_name="Pedro López")])
    assert len(bulk.people) == 2


def test_bulk_create_empty_raises():
    with pytest.raises(ValidationError):
        PersonBulkCreate(people=[])


def test_bulk_create_too_many_raises():
    with pytest.raises(ValidationError):
        PersonBulkCreate(people=[PersonCreate(full_name=f"Person {i}") for i in range(501)])


def test_search_params_page_size_max():
    with pytest.raises(ValidationError):
        SearchParams(page_size=101)


def test_search_params_defaults():
    p = SearchParams()
    assert p.page == 1
    assert p.page_size == 10
    assert p.fallecido is None


def test_search_params_document_id_strips_non_digits():
    p = SearchParams(document_id="V-12345678")
    assert p.document_id == "12345678"


def test_search_params_invalid_tipo():
    with pytest.raises(ValidationError):
        SearchParams(tipo_instalacion="farmacia")
