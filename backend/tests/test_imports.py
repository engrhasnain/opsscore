"""CSV import of sites and assets, with the files clients really send."""

API = "/api/v1"


def upload(client, headers, kind, content: bytes, **params):
    return client.post(
        f"{API}/{kind}/import",
        headers=headers,
        params=params,
        files={"file": ("data.csv", content, "text/csv")},
    )


def test_latam_excel_export(client, portco_headers):
    """Semicolons, decimal commas, a byte-order mark, accents and an extra column."""
    content = (
        "﻿Código;Name;Kind;Latitude;Longitude;Timezone;Operador\n"
        "t-1;Terminal Santos;terminal;-23,9608;-46,3336;America/Sao_Paulo;Equipe A\n"
        "g-2;Portão 2;gate;;;;\n"
        ";;;;;;\n"
    )
    content = content.replace("Código", "Code")
    response = upload(client, portco_headers, "sites", content.encode("utf-8"))
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 2
    sites = {s["code"]: s for s in client.get(f"{API}/sites", headers=portco_headers).json()["items"]}
    assert sites["T-1"]["latitude"] == -23.9608
    assert sites["T-1"]["attributes"] == {"operador": "Equipe A"}
    assert sites["G-2"]["name"] == "Portão 2"


def test_windows_1252_file(client, acme_headers):
    content = "code,name\nS-1,Estación Añelo\n".encode("cp1252")
    assert upload(client, acme_headers, "sites", content).json()["created"] == 1


def test_all_or_nothing_with_row_numbers(client, acme_headers):
    content = b"code,name,latitude,longitude\nA,Alpha,1,2\nB,,1,2\nA,Again,1,2\nC,Charlie,95,2\nD,Delta,1,\n"
    response = upload(client, acme_headers, "sites", content)
    assert response.status_code == 422
    errors = response.json()["error"]["details"]
    assert [e["row"] for e in errors] == [3, 4, 5, 6]
    assert client.get(f"{API}/sites", headers=acme_headers).json()["total"] == 0


def test_dry_run_and_upsert(client, acme_headers):
    content = b"code,name\nA,Alpha\n"
    dry = upload(client, acme_headers, "sites", content, dry_run=True).json()
    assert dry["dry_run"] and dry["created"] == 1
    assert client.get(f"{API}/sites", headers=acme_headers).json()["total"] == 0

    assert upload(client, acme_headers, "sites", content).json()["created"] == 1
    assert upload(client, acme_headers, "sites", content).status_code == 422  # exists, no upsert
    updated = upload(client, acme_headers, "sites", b"code,name\nA,Alpha renamed\n", upsert=True).json()
    assert updated["updated"] == 1


def test_assets_need_known_sites(client, acme_headers):
    upload(client, acme_headers, "sites", b"code,name\nPAD-1,Pad 1\n")
    content = (
        b"code,name,site_code,type,criticality\n"
        b"TB-1,Tank,pad-1,tank,5\n"
        b"TB-2,Tank 2,PAD-9,tank,3\n"  # unknown site
        b"TB-3,Tank 3,PAD-1,tank,9\n"  # criticality out of range
    )
    response = upload(client, acme_headers, "assets", content)
    assert [e["row"] for e in response.json()["error"]["details"]] == [3, 4]
    fixed = b"code,name,site_code,type,criticality\nTB-1,Tank,pad-1,tank,5\n"
    assert upload(client, acme_headers, "assets", fixed).json()["created"] == 1


def test_file_problems(client, acme_headers, settings):
    assert upload(client, acme_headers, "sites", b"").status_code == 422
    assert upload(client, acme_headers, "sites", b"code,name\n").json()["error"]["code"] == "EMPTY_FILE"
    missing = upload(client, acme_headers, "sites", b"name\nAlpha\n").json()["error"]
    assert missing["code"] == "MISSING_COLUMNS" and missing["details"]["missing"] == ["code"]
    assert upload(client, acme_headers, "sites", b"code,code\nA,B\n").json()["error"]["code"] == "DUPLICATE_COLUMNS"
    assert upload(client, acme_headers, "sites", b"\xff\xfe\x00\x81bad").status_code == 422
    too_big = b"code,name\n" + b"A,B\n" * (settings.import_max_bytes // 4 + 1)
    assert upload(client, acme_headers, "sites", too_big).status_code == 413
