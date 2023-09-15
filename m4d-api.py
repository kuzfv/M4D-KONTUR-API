import requests
import base64
import json
import time
import os

URL = "https://m4d-api-staging.testkontur.ru"  # Staging
# URL = "https://m4d-api.kontur.ru"  # Production
APIKEY = os.getenv("M4D-KONTUR-APIKEY")  # Личный APIKEY


class CustomError(Exception):
    """Класс для описания ошибок"""


def base64_encoder(filepath, decode=False):
    """Конвертация контента файла в Base64"""

    with open(filepath, "rb") as file:
        if decode:
            return base64.b64encode(file.read()).decode()
        else:
            return base64.b64encode(file.read())


def to_camel_case_converter(string):
    """Конвертация snake_case строки в CamelCase строку"""

    return "".join(word.title() for word in string.split("_"))

####
# Работа с организациями
####


def get_organizations():
    """Список доступных организаций"""

    organizations_req = requests.get(f"{URL}/v1/organizations",
                                     headers={"X-Kontur-Apikey": APIKEY})
    if organizations_req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /organizations. {organizations_req.text}")
    if organizations_req.json()["totalCount"] == 0:
        raise CustomError("No organizations available. Please follow the instruction https://clck.ru/35aL5Z")
    return organizations_req.json()


def set_organization_id(count=1):
    """Выбор организации"""

    organizations = get_organizations()
    if count > organizations["totalCount"]:
        raise CustomError(
            f"You have only {organizations['totalCount']} organizations. Please change the count parameter")
    return organizations["organizations"]["items"][count - 1]['id']


def get_organization_info(org_id):
    """Получение информации об организации"""

    organizations = get_organizations()
    for organization in organizations["organizations"]["items"]:
        if organization['id'] == org_id:
            return organization


####
# Реализация синхронных методов API
####


def search_poas(sync_timeout_ms=1000, next_token=None, **params):
    """Поиск МЧД. Возможные параметры описаны в документации https://clck.ru/35aL42"""

    req = requests.get(f"{URL}/v1/organizations/{organization_id}/poas",
                       headers={"X-Kontur-Apikey": APIKEY},
                       params={to_camel_case_converter(key): value for key, value in params.items()})
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /poas. {req.text}")
    return req


def get_poa_metainfo(poa_number, sync_timeout_ms=1000):
    """Получение метаинформации об МЧД"""

    req = requests.get(f"{URL}/v1/organizations/{organization_id}/poas/{poa_number}",
                       headers={"X-KONTUR-APIKEY": APIKEY},
                       params={"SyncTimeoutMs": sync_timeout_ms})
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /poas/poa_number. {req.text}")
    return req.json()


def get_archive(poa_number):
    """Получение архива с файлами МЧД"""

    with open("./archive.zip", "wb") as archive:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/poas/{poa_number}/zip-archive",
                           headers={"X-KONTUR-APIKEY": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /zip-archive. {req.text}")
        archive.write(req.content)


def get_revocation_xml_file(poa_number, reason=None):
    """Получение файла отзыва МЧД"""

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


def validation_poa(principal: dict, poa_identity={}, representative={},
                   thumbprint=None, certificate_path=None, poa_files=[],
                   sync_timeout_ms=1000):
    """Валидация МЧД"""

    payload = {
        "parameters": {
            "poaIdentity": None,
            "principal": {
                "inn": principal["inn"],
                "kpp": principal["kpp"]
            },
            "representative": {
                "requisites": {},
                "certificate": {}
            }
        },
        "poaFiles": {},
        "syncTimeoutMs": sync_timeout_ms
    }

    # Сначала валидация переданных параметров
    if not poa_files:
        if not poa_identity:
            raise CustomError("Должен быть указан параметр 'poaIdentity' или 'poaFiles'")
        payload["parameters"]["poaIdentity"] = {"number": poa_identity["number"],
                                                "principalInn": poa_identity["inn"]}
        payload["poaFiles"] = None
    else:
        if poa_identity:
            raise CustomError("Должен быть указан только один параметр 'poaIdentity' или 'poaFiles'")
        payload["poaFiles"] = {"poaContent": base64_encoder(poa_files[0], True),
                               "signatureContent": base64_encoder(poa_files[1], True)}
        payload["poaIdentity"] = None

    if not representative:
        if not thumbprint:
            if not certificate_path:
                raise CustomError("Должен быть указан параметр 'representative', 'thumbprint' или 'certificate_path'")
            else:
                payload["parameters"]["representative"]["certificate"]["body"] = base64_encoder(certificate_path, True)
                payload["parameters"]["representative"]["requisites"] = None
        else:
            if certificate_path:
                raise CustomError("Должен быть указан только один параметр 'thumbprint' или 'certificate_path'")
            payload["parameters"]["representative"]["certificate"]["thumbprint"] = thumbprint
            payload["parameters"]["representative"]["requisites"] = None
    else:
        if thumbprint:
            raise CustomError("Должен быть указан только один параметр 'representative' или 'thumbprint'")
        if certificate_path:
            raise CustomError("Должен быть указан только один параметр 'representative' или 'certificate_path'")
        payload["parameters"]["representative"]["requisites"] = representative
        payload["parameters"]["representative"]["certificate"] = None

    req = requests.post(f"{URL}/v1/organizations/{organization_id}/poas/validate-local",
                        headers={"X-KONTUR-APIKEY": APIKEY},
                        json=payload)
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /validate-local. {req.text}")
    return req.json()


def create_xml_from_json(json_data, filename="poa"):
    """Формирование XML файла МЧД из JSON"""

    req = requests.post(f"{URL}/v1/organizations/{organization_id}/poas/form-xml",
                        headers={"X-KONTUR-APIKEY": APIKEY},
                        json=json_data)
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /form-xml. {req.text}")
    with open(f"./{filename}.xml", "wb") as poa:
        poa.write(req.content)


def create_xml_from_json_file(json_filepath, filename="poa"):
    """Формирование XML файла МЧД из JSON файла"""

    with open(json_filepath, "rb") as file:
        create_xml_from_json(json.loads(file.read()), filename)


def create_draft_from_xml_file(path_to_file, send_to_sign=False):
    """Создание черновика из XML файла"""

    with open(path_to_file, "rb") as xml:
        req = requests.post(f"{URL}/v1/organizations/{organization_id}/drafts",
                            headers={"X-KONTUR-APIKEY": APIKEY},
                            data={"sendToSign": send_to_sign},
                            files={"poa": xml.read()})
    if req.status_code != 200:
        raise CustomError(f"Unsuccessful HTTP request /drafts. {req.text}")
    return req.json()["draftId"]


####
# Работа с асинхронными методами API + поллинг до терминального статуса
####


def async_registration(poa_path, signature_path, polling_time_sec=1):
    """Регистрация МЧД"""

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
    """Скачивание МЧД"""

    def return_meta(operation_id, filename="poa_archive"):
        """Получение метаинформации об МЧД"""

        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/downloads/{operation_id}/meta",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /meta. {req.text}")
        return req.json()

    def create_archive(operation_id, filename="archive"):
        """Получение архива с файлами МЧД"""

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
    """Импорт МЧД"""

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
    """Отзыв МЧД"""

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
        if req.json()['status'] in ("done", "error"):
            return req.json()
        time.sleep(polling_time_sec)


def async_validation(principal: dict, poa_identity={}, representative={},
                     thumbprint=None, certificate_path=None, poa_files=[],
                     polling_time_sec=1):
    """Валидация МЧД"""

    payload = {
        "parameters": {
            "poaIdentity": None,
            "principal": {
                "inn": principal["inn"],
                "kpp": principal["kpp"]
            },
            "representative": {
                "requisites": {},
                "certificate": {}
            }
        },
        "poaFiles": {}
    }

    # Сначала валидация переданных параметров
    if not poa_files:
        if not poa_identity:
            raise CustomError("Должен быть указан параметр 'poaIdentity' или 'poaFiles'")
        payload["parameters"]["poaIdentity"] = {"number": poa_identity["number"],
                                                "principalInn": poa_identity["inn"]}
        payload["poaFiles"] = None
    else:
        if poa_identity:
            raise CustomError("Должен быть указан только один параметр 'poaIdentity' или 'poaFiles'")
        payload["poaFiles"] = {"poaContent": base64_encoder(poa_files[0], True),
                               "signatureContent": base64_encoder(poa_files[1], True)}
        payload["poaIdentity"] = None

    if not representative:
        if not thumbprint:
            if not certificate_path:
                raise CustomError("Должен быть указан параметр 'representative', 'thumbprint' или 'certificate_path'")
            else:
                payload["parameters"]["representative"]["certificate"]["body"] = base64_encoder(certificate_path, True)
                payload["parameters"]["representative"]["requisites"] = None
        else:
            if certificate_path:
                raise CustomError("Должен быть указан только один параметр 'thumbprint' или 'certificate_path'")
            payload["parameters"]["representative"]["certificate"]["thumbprint"] = thumbprint
            payload["parameters"]["representative"]["requisites"] = None
    else:
        if thumbprint:
            raise CustomError("Должен быть указан только один параметр 'representative' или 'thumbprint'")
        if certificate_path:
            raise CustomError("Должен быть указан только один параметр 'representative' или 'certificate_path'")
        payload["parameters"]["representative"]["requisites"] = representative
        payload["parameters"]["representative"]["certificate"] = None

    req = requests.post(f"{URL}/v1/organizations/{organization_id}/operations/validations",
                        headers={"X-Kontur-Apikey": APIKEY},
                        json=payload)
    if req.status_code != 201:
        raise CustomError(f"Unsuccessful HTTP request /validations. {req.text}")
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/validations/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise CustomError(f"Unsuccessful HTTP request /revocations/operation_id. {req.text}")
        if req.json()['status'] in ("done", "error"):
            return req.json()
        time.sleep(polling_time_sec)


if __name__ == "__main__":
    organization_id = set_organization_id()
    # poa_identity = {"number": "31cc6eee-b565-4266-9097-2a8ac00ff444", "inn": "4401165141"}
    # principal = {"inn": "4401165141", "kpp": "440101001"}
    # representative = {"name": "Иван", "surname": "Иванов", "snils": "252-639-136 73", "inn": "477704523710"}
