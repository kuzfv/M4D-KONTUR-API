import requests
import base64
import json
import time
import os


URL = "https://m4d-api-staging.testkontur.ru"  # Staging
# URL = "https://m4d-api.kontur.ru"  # Production
APIKEY = os.getenv("M4D-KONTUR-APIKEY")  # Set the environment variable or put you APIKEY here


class CustomError(Exception):
    """Класс для описания ошибок"""


def base64_encoder(filepath):
    with open(filepath, "rb") as file:
        return base64.b64encode(file.read())


####
# Works with organization
####


def get_organizations():
    """List of available organizations"""

    organizations_req = requests.get(f"{URL}/v1/organizations",
                                     headers={"X-Kontur-Apikey": APIKEY})
    if organizations_req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /organizations. {organizations_req.text}")
    if organizations_req.json()["totalCount"] == 0:
        raise CustomError("No organizations available. Please follow the instruction https://support.kontur.ru/pages/viewpage.action?pageId=102898898")
    return organizations_req.json()


def set_organization_id(count=1):
    """Chose organization"""

    organizations = get_organizations()
    if count < 1:
        raise CustomError("Count parameter must be greater than 1")
    if count > organizations["totalCount"]:
        raise CustomError(f"You have only {organizations['totalCount']} organizations. Please change the count parameter")    
    return organizations["organizations"]["items"][count-1]['id']


def get_organization_info(org_id):
    """Get information about organization"""
    
    organizations = get_organizations()
    for organization in organizations["organizations"]["items"]:
        if organization['id'] == org_id:
            return organization


####
# Sync methods
####


def search_poas(sync_timeout_ms=1000, next_token=None, **params):
    """Search all poas of organization. Check the possible parameters here https://developer.kontur.ru/doc/m4d-api/method?type=get&path=%2Fv1%2Forganizations%2F%7BorganizationId%7D%2Fpoas"""
    
    req = requests.get(f"{URL}/v1/organizations/{organization_id}/poas",
                       headers={"X-Kontur-Apikey": APIKEY},
                       params=params)
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /poas. {req.text}")


def get_poa_metainfo(poa_number, sync_timeout_ms=1000):
    """Get metainformation of poa"""

    req = requests.get(f"{URL}/v1/organizations/{organization_id}/poas/{poa_number}",
                       headers={"X-KONTUR-APIKEY": APIKEY},
                       params={"SyncTimeoutMs": sync_timeout_ms})
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /poas/poa_number. {req.text}")
    return req.json()


def get_archive(poa_number):
    """Get ZIP archive of poa"""

    with open("./archive.zip", "wb") as archive:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/poas/{poa_number}/zip-archive",
                           headers={"X-KONTUR-APIKEY": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /zip-archive. {req.text}")
        archive.write(req.content)


def get_revocation_xml_file(poa_number, reason):
    """Get revocation file of poa"""

    organization_info = get_organization_info(organization_id)['legalEntity']
    poa_info = get_poa_metainfo(poa_number)
    req = requests.post(f"{URL}/v1/organizations/{organization_id}/poas/{poa_number}/revocation/form-xml",
                        headers={"X-KONTUR-APIKEY": APIKEY},
                        json={"reason": reason,
                              "inn": organization_info["inn"],
                              "ogrn": organization_info["ogrn"],
                              "kpp": organization_info["kpp"],
                              "name": organization_info['fullName'],
                              "poaType": poa_info["poa"]['poaType']})
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /revocation/form-xml. {req.text}")
    with open(f"./revocation_poa_{poa_number}.xml", "wb") as xml:
        xml.write(req.content)    


def validation_poa_requisites(principal, representative, poa_identity={},
                              thumbprint=None, certificate_path=None, poa_path=None, signature_path=None,
                              sync_timeout_ms=1000):  # LATER. TOO MUCH CASES - 6
    """Validation of poa"""

    """
poaIdentity + thumbprint
poaIdentity + body
poaIdentity + requisites

poaFiles + thumbprint
poaFiles + body
poaFiles + requisites
    """
    
    payload = {
        "parameters": {
            "poaIdentity": {
                "number": poa_identity.get("number"),
                "principalInn": poa_identity.get("inn")
                },
            "principal": {
                "inn": principal["inn"],
                "kpp": principal["kpp"]
                },
            "representative": {
                "requisites": {
                    "name": representative["name"],
                    "surname": representative["surname"],
                    "middlename": representative["middlename"],
                    "snils": representative["snils"],
                    "inn": representative["inn"],
                    "innUl": representative.get("innUl"),
                    "kpp": representative.get("kpp")
                    },
                "certificate": {
                    "thumbprint": thumbprint,
                    "body": certificate_path
                    }
                }
            },
        "poaFiles": {
            "poaContent": base64_encoder(poa_path),
            "signatureContent": base64_encoder(signature_path)
            },
        "syncTimeoutMs": sync_timeout_ms
        }

    req = requests.post(f"{URL}/v1/organizations/{organization_id}/poas/validate-local",
                        headers={"X-KONTUR-APIKEY": APIKEY},
                        json=payload)
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /validate-local. {req.text}")
    return req.json()


def generate_xml_from_json(json_data, filename="poa"):
    """Generate XML file of poa from JSON data"""

    req = requests.post(f"{URL}/v1/organizations/{organization_id}/poas/form-xml",
                        headers={"X-KONTUR-APIKEY": APIKEY},
                        json=json_data)
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /form-xml. {req.text}")
    with open(f"./{filename}.xml", "wb") as poa:
        poa.write(req.content)


def generate_xml_from_json_file(json_filepath):
    """Generate XML file of poa from JSON file"""

    with open(json_filepath, "rb") as file:
        generate_xml_from_json(json.loads(file))


def create_draft_from_xml_file(path_to_file, send_to_sign=False):
    """Create draft of poa from XML file"""
    
    with open(path_to_file, "rb") as xml:
        req = requests.post(f"{URL}/v1/organizations/{organization_id}/drafts",
                            headers={"X-KONTUR-APIKEY": APIKEY},
                            data={"sendToSign": send_to_sign},
                            files={"poa": xml.read()})
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /drafts. {req.text}")
    return req.json()["draftId"]


####
# Async methods
####


def async_registration(poa_path, signature_path, polling_time_sec=1):
    """Registration of poa with polling until terminate status"""

    assert isinstance(polling_time_sec, (int, float)) and polling_time_sec > 0, "'polling_time_sec' must be integer or float type above zero"

    with open(poa_path, "rb") as poa, open(signature_path, "rb") as sig:
        req = requests.post(f"{URL}/v1/organizations/{organization_id}/operations/registrations",
                      headers={"X-Kontur-Apikey": APIKEY},
                      files={"poa": poa.read(), "signature": sig.read()})
        if req.status_code != 201:
            raise CustomError(f"Unsuccessful HTTP request /registrations. {req.text}")
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/registrations/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /registrations/operation_id. {req.text}")
        if req.json()['status'] in ("done", "error"):
            return req.json()
        time.sleep(polling_time_sec)


def async_download(number, principal_inn, inn, datatype="archive", polling_time_sec=1):
    """Download of poa with polling until terminate status"""

    assert datatype in ("meta", "archive"), "'datatype' variable must be 'archive' or 'meta' only"
    assert isinstance(polling_time_sec, (int, float)) and polling_time_sec > 0, "'polling_time_sec' must be integer or float type above zero"

    def return_meta(operation_id, filename="poa_archive"):
        """Get metainformation of poa"""
        
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/downloads/{operation_id}/meta",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /meta. {req.text}")
        return req.json()

    def create_archive(operation_id, filename="archive"):
        """Create ZIP archive with poa files"""
        
        req = requests.get(f"{URL}//v1/organizations/{organization_id}/operations/downloads/{operation_id}/zip-archive",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /zip-archive. {req.text}")
        with open(f"{filename}.zip", "wb") as archive:
            archive.write(req.content)

    payload = {
        "parameters": {
            "poaIdentity": {
                "number": number,
                "principalInn": principal_inn
                },
            "representativeRequisites": {
                "inn": inn
                }
            }
        }
    
    req = requests.post(f"{URL}/v1/organizations/{organization_id}/operations/downloads",
                        headers={"X-Kontur-Apikey": APIKEY},
                        json=payload)
    if req.status_code != 201:
        raise CustomError(f"Unsuccessful HTTP request /downloads. {req.text}")
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/downloads/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /downloads/operation_id. {req.text}")
        if req.json()['status'] == "done":
            if datatype == "archive":
                return create_archive(operation_id)
            else:
                return return_meta(operation_id)
        elif req.json()['status'] == "error":
            return req.json()
        time.sleep(polling_time_sec)


def async_import(number, principal_inn, inn, polling_time_sec=1):
    """Import of poa with polling until terminate status"""

    assert isinstance(polling_time_sec, (int, float)) and polling_time_sec > 0, "'polling_time_sec' must be integer or float type above zero"
    
    payload = {
        "parameters": {
            "poaIdentity": {
                "number": number,
                "principalInn": principal_inn
                },
            "representativeRequisites": {
                "inn": inn
                }
            }
        }

    req = requests.post(f"{URL}/v1/organizations/{organization_id}/operations/imports",
                        headers={"X-Kontur-Apikey": APIKEY},
                        json=payload)
    if req.status_code != 201:
        raise CustomError(f"Unsuccessful HTTP request /imports. {req.text}")
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/imports/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /imports/operation_id. {req.text}")
        if req.json()['status'] in ("done", "error"):
            return req.json()
        time.sleep(polling_time_sec)


def async_revocation(revocation_file_path, signature_path, polling_time_sec=1):
    """Revocation of poa with polling until terminate status"""

    assert isinstance(polling_time_sec, (int, float)) and polling_time_sec > 0, "'polling_time_sec' must be integer or float type above zero"

    with open(revocation_file_path, "rb") as revocation, open(signature_path, "rb") as sig:
        req = requests.post(f"{URL}/v1/organizations/{organization_id}/operations/revocations",
                      headers={"X-Kontur-Apikey": APIKEY},
                      files={"revocation": revocation.read(), "signature": sig.read()})
        if req.status_code != 201:
            raise CustomError(f"Unsuccessful HTTP request /revocations. {req.text}")
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/revocations/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /revocations/operation_id. {req.text}")
        print(req.json()['status'])
        if req.json()['status'] in ("done", "error"):
            return req.json()
        time.sleep(polling_time_sec)


def async_validation():  # LATER. TOO MUCH CASES - 6
    pass


if __name__ == "__main__":
    organization_id = set_organization_id()
