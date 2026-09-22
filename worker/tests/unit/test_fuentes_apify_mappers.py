"""Tests de los mapeos puros item de Apify -> RegistroBruto (sin red ni BD),
con fixtures basados en los ejemplos de salida documentados en apify.com
(2026-09-22) de cada Actor."""

from radar.fuentes.apify_facebook import pagina_a_registro
from radar.fuentes.apify_linkedin import empresa_a_registro
from radar.fuentes.apify_maps import lugar_a_registro

# ---------- apify_maps (compass/crawler-google-places) ----------


def test_maps_lugar_completo():
    item = {
        "title": "Fontanería Pérez", "address": "Calle Sierpes 1, Sevilla", "phone": "+34 954 11 22 33",
        "website": "https://fontaneriaperez.es", "categoryName": "Fontanero", "totalScore": 4.5,
        "location": {"lat": 37.389, "lng": -5.995}, "placeId": "ChIJabc123", "permanentlyClosed": False,
    }
    r = lugar_a_registro(item)
    assert r is not None and r.fuente == "apify_google_maps" and r.id_externo == "ChIJabc123"
    assert r.campos.nombre_comercial == "Fontanería Pérez"
    assert r.campos.telefonos == ["+34 954 11 22 33"]
    assert r.campos.lat == 37.389 and r.campos.lon == -5.995
    assert r.campos.web == "https://fontaneriaperez.es"


def test_maps_sin_nombre_o_cerrado_no_se_guarda():
    assert lugar_a_registro({"title": "", "placeId": "x"}) is None
    assert lugar_a_registro({"title": "Cerrado SL", "permanentlyClosed": True}) is None


# ---------- apify_linkedin (automation-lab/linkedin-company-scraper) ----------


def test_linkedin_empresa_completa():
    item = {
        "name": "Stripe", "linkedinUrl": "https://www.linkedin.com/company/stripe", "website": "https://stripe.com",
        "industry": "Technology", "street": "354 Oyster Point Blvd", "city": "South San Francisco",
        "state": "California", "country": "US", "postalCode": "94080", "headquarters": "South San Francisco, California",
    }
    r = empresa_a_registro(item)
    assert r is not None and r.fuente == "linkedin"
    assert r.campos.nombre_comercial == "Stripe"
    assert r.campos.domicilio == "354 Oyster Point Blvd"
    assert r.campos.municipio == "South San Francisco" and r.campos.web == "https://stripe.com"
    assert r.campos.extra["industria"] == "Technology"


def test_linkedin_usa_headquarters_si_no_hay_calle():
    item = {"name": "Acme", "headquarters": "Madrid, España"}
    r = empresa_a_registro(item)
    assert r is not None and r.campos.domicilio == "Madrid, España"


def test_linkedin_sin_nombre_no_se_guarda():
    assert empresa_a_registro({"resolutionConfidence": "none"}) is None


# ---------- apify_facebook (apify/facebook-pages-scraper) ----------


def test_facebook_pagina_completa():
    item = {
        "facebookUrl": "https://www.facebook.com/example", "title": "Reformas Example", "pageId": "1000777",
        "address": "123 Main St, Sevilla, España", "phone": "+1-555-0123", "email": "contact@example.com",
        "websites": ["https://example.com"], "categories": ["Business"],
    }
    r = pagina_a_registro(item)
    assert r is not None and r.fuente == "facebook" and r.id_externo == "1000777"
    assert r.campos.nombre_comercial == "Reformas Example"
    assert r.campos.telefonos == ["+1-555-0123"] and r.campos.emails == ["contact@example.com"]
    assert r.campos.web == "https://example.com"


def test_facebook_sin_nombre_no_se_guarda():
    assert pagina_a_registro({"address": "algo"}) is None
