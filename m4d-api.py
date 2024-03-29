from requests import HTTPError
from pprint import pprint
import subprocess
import requests
import secrets
import base64
import json
import time
import bs4
import os
import re


ENV = False
URL = "https://m4d-api-staging.testkontur.ru"
APIKEY = os.getenv("M4D-KONTUR-APIKEY")
EXTERN_TOKEN = None
EXTERN_REFRESH_TOKEN = None
EXTERN_TOKEN_TIME = 0  # Пока не используется


class CustomError(Exception):
    """Класс для описания ошибок"""


def change_environment():
    """Изменение окружения"""

    global ENV, URL, APIKEY, organization_id

    ENV = not ENV

    if ENV:
        URL = "https://m4d-api.kontur.ru" 
        APIKEY = secrets.APIKEY
        organization_id = secrets.organization_id
        print("Production environment using")
    else:
        URL = "https://m4d-api-staging.testkontur.ru"
        APIKEY = os.getenv("M4D-KONTUR-APIKEY")
        organization_id = set_organization_id()
        print("Staging environment using")


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


def get_extern_account_id():
    """Получение Id аккаунта в Экстерне"""
    
    req = requests.get("https://extern-api.testkontur.ru/v1",
                       headers={"Authorization": f"Bearer {EXTERN_TOKEN}"})
    if req.status_code != 200:
        raise HTTPError(f"Unsuccessful HTTP request /v1.\n{req.text}")
    return req.json()["accounts"][0]["id"]


def get_extern_token():
    """Получение ExternOIDCToken по Device Flow"""
    # Нужен только для регистрации МЧД ФНС и ФСС

    from webbrowser import open_new_tab
    global EXTERN_TOKEN, EXTERN_REFRESH_TOKEN

    # Тут еще функция проверки срока действия токена
    # Если жив - вернуть текущий. Если нет, запросить новый

    def is_alive_token():
        pass

    identity_url = "https://identity.testkontur.ru"
    req = requests.post(f"{identity_url}/connect/deviceauthorization",
                        data={"client_id": secrets.client_id,
                              "client_secret": secrets.client_secret,
                              "scope": "extern.api offline_access"})
    if req.status_code != 200:
        raise HTTPError(f"{req.text}")
    auth_data = req.json()

    open_new_tab(auth_data['verification_uri_complete'])
    device_code = auth_data["device_code"]

    while True:
        req = requests.post(f"{identity_url}/connect/token",
                            data={"client_id": secrets.client_id,
                                  "client_secret": secrets.client_secret,
                                  "device_code": f"{device_code}",
                                  "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                  "scope": "extern.api offline_access"})
        if req.status_code != 200:
            if req.status_code == 400 and req.json()["error"] == "authorization_pending":
                print("authorization_pending")
                time.sleep(3)
            else:
                raise HTTPError(f"{req.text}")
        else:
            EXTERN_TOKEN = req.json()["access_token"]
            EXTERN_REFRESH_TOKEN = req.json()["refresh_token"]
            return EXTERN_TOKEN


def refresh_extern_token():
    """Обновление токена по Refresh Token"""

    global EXTERN_TOKEN, EXTERN_REFRESH_TOKEN

    identity_url = "https://identity.testkontur.ru"
    req = requests.post(f"{identity_url}/connect/token",
                        data={"client_id": secrets.client_id,
                              "client_secret": secrets.client_secret,
                              "scope": "extern.api offline_access",
                              "grant_type": "refresh_token",
                              "refresh_token": EXTERN_REFRESH_TOKEN})
    if req.status_code != 200:
        raise HTTPError(f"{req.text}")
    else:
        EXTERN_TOKEN = req.json()["access_token"]
        EXTERN_REFRESH_TOKEN = req.json()["refresh_token"]
        return EXTERN_TOKEN


def sign_file(filepath, rawsign=False):
    """Подписание файла выбранным сертификатом"""
    # Указание сертификата в secrets.py
    # Для DetachesCMS подписи отпечаток сертификата
    # Для RAW подписи FQCN имя контейнера

    if rawsign:
        # Нужна утилита csptest
        if not os.path.exists("./csptest.exe"):
            raise CustomError("Не найдена утилита csptest")
        command = f'csptest -keys -sign GOST12_256 -cont "\{secrets.container_name}" -keytype exchange -in {filepath} -out {filepath}.sig'
    else:
        # Нужна утилита cryptcp
        if not os.path.exists("./cryptcp.x64.exe"):
            raise CustomError("Не найдена утилита cryptcp")
        command = f'cryptcp.x64.exe -sign -thumbprint {secrets.certificate_thumbprint} {filepath} -der -strict -detached -fext .sig'
    subprocess.call(command, shell=True)


####
# Работа с организациями
####


def get_organizations():
    """Список доступных организаций"""

    organizations_req = requests.get(f"{URL}/v1/organizations",
                                     headers={"X-Kontur-Apikey": APIKEY})
    if organizations_req.status_code != 200:
        raise HTTPError(f"Unsuccessful HTTP request /organizations. {organizations_req.text}")
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


def get_operation_status(operation_id, operation_type="r"):
    """Получение данных об операции"""

    operations = {"r": "registrations", "i": "imports", "v": "validations", "rv": "revocations", "d": "downloads"}
    req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/{operations[operation_type]}/{operation_id}",
                       headers={"X-Kontur-Apikey": APIKEY})
    if req.status_code != 200:
        raise HTTPError(f"Unsuccessful HTTP request.\n{req.text}")
    return req.json()


####
# Реализация синхронных методов API
####


def search_poas(sync_timeout_ms=1000, next_token=None, **params):
    """Поиск МЧД. Возможные параметры описаны в документации https://clck.ru/35aL42"""

    req = requests.get(f"{URL}/v1/organizations/{organization_id}/poas",
                       headers={"X-Kontur-Apikey": APIKEY},
                       params={to_camel_case_converter(key): value for key, value in params.items()})
    if req.status_code != 200:
        raise HTTPError(f"Unsuccessful HTTP request /poas.\n{req.text}")
    return req


def get_poa_metainfo(poa_number, sync_timeout_ms=1000):
    """Получение метаинформации об МЧД"""

    req = requests.get(f"{URL}/v1/organizations/{organization_id}/poas/{poa_number}",
                       headers={"X-KONTUR-APIKEY": APIKEY},
                       params={"SyncTimeoutMs": sync_timeout_ms})
    if req.status_code != 200:
        raise HTTPError(f"Unsuccessful HTTP request /poas/poa_number.\n{req.text}")
    return req.json()


def get_archive(poa_number):
    """Получение архива с файлами МЧД"""

    with open(f"./poa_{poa_number}.zip", "wb") as archive:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/poas/{poa_number}/zip-archive",
                           headers={"X-KONTUR-APIKEY": APIKEY})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /zip-archive.\n{req.text}")
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
        raise HTTPError(f"Unsuccessful HTTP request /revocation/form-xml.\n{req.text}")
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
        raise HTTPError(f"Unsuccessful HTTP request /validate-local.\n{req.text}")
    return req.json()


def create_xml_from_json(json_data, filename="poa"):
    """Формирование XML файла МЧД из JSON"""

    req = requests.post(f"{URL}/v1/organizations/{organization_id}/poas/form-xml",
                        headers={"X-KONTUR-APIKEY": APIKEY},
                        json=json_data)
    if req.status_code != 200:
        raise HTTPError(f"Unsuccessful HTTP request /form-xml.\n{req.text}")
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
        raise HTTPError(f"Unsuccessful HTTP request /drafts.\n{req.text}")
    return req.json()["draftId"]


def download_poa_draft(poa_number):
    """ПЛАТНАЯ ФИЧА!! Скачивание черновика МЧД"""

    with open(f"draft_{poa_number}.xml", "wb") as poa:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/drafts/{poa_number}/xml",
                           headers={"X-KONTUR-APIKEY": APIKEY})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /poa_number/xml.\n{req.text}")
        poa.write(req.content)


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
            raise HTTPError(f"Unsuccessful HTTP request /registrations.\n{req.text}")
    print(req.json())
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/registrations/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /registrations/operation_id.\n{req.text}")
        if req.json()['status'] in ("done", "error"):
            return req.json()
        time.sleep(polling_time_sec)


def async_download(number, principal_inn, inn, datatype="archive", polling_time_sec=1):
    """Скачивание МЧД"""

    def return_meta(operation_id):
        """Получение метаинформации об МЧД"""

        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/downloads/{operation_id}/meta",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /meta.\n{req.text}")
        return req.json()

    def create_archive(operation_id):
        """Получение архива с файлами МЧД"""

        req = requests.get(f"{URL}//v1/organizations/{organization_id}/operations/downloads/{operation_id}/zip-archive",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /zip-archive.\n{req.text}")
        with open(f"poa_{number}.zip", "wb") as archive:
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
    print(payload)
    req = requests.post(f"{URL}/v1/organizations/{organization_id}/operations/downloads",
                        headers={"X-Kontur-Apikey": APIKEY},
                        json=payload)
    if req.status_code != 201:
        raise HTTPError(f"Unsuccessful HTTP request /downloads.\n{req.text}")
    print(req.json())
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/downloads/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /downloads/operation_id.\n{req.text}")
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
        raise HTTPError(f"Unsuccessful HTTP request /imports.\n{req.text}")
    print(req.json())
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/imports/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /imports/operation_id.\n{req.text}")
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
            raise HTTPError(f"Unsuccessful HTTP request /revocations.\n{req.text}")
    print(req.json())
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/revocations/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /revocations/operation_id.\n{req.text}")
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
        raise HTTPError(f"Unsuccessful HTTP request /validations.\n{req.text}")
    print(req.json())
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/validations/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /validations/operation_id.\n{req.text}")
        if req.json()['status'] in ("done", "error"):
            return req.json()
        time.sleep(polling_time_sec)


def async_registration_fns_poa(poa_path, signature_path, certificate_path, fns_code="0087", polling_time_sec=1):
    """Регистрация МЧД для ФНС 5.01, 5.02"""
    
    organization = get_organization_info(organization_id)["legalEntity"]
    payload ={
         "fnsCode": fns_code,
         "payerInn": organization["inn"],
         "payerKpp": organization["kpp"],
         "payerOgrn": organization["ogrn"],
         "payerSnils": "17097865012",
         "senderInn": organization["inn"],
         "senderKpp": organization["kpp"],
         "externAccountId": secrets.extern_account_id,
         "senderCertificateContent": base64_encoder(certificate_path, True),
         "senderIpAddress": requests.get("https://api.ipify.org").text
         }
    with open(poa_path, "rb") as poa, open(signature_path, "rb") as sig:
        req = requests.post(f"{URL}/v1/organizations/{organization_id}/operations/fns/registrations",
                            headers={"X-Kontur-Apikey": APIKEY,
                                     "ExternOidcToken": EXTERN_TOKEN},
                            data=payload,
                            files={"poa": poa.read(),
                                   "signature": sig.read()})
    if req.status_code != 201:
        raise HTTPError(f"Unsuccessful HTTP request /fns/registrations.\n{req.text}")
    print(req.json())
    operation_id = req.json()["id"]

    while True:
        req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/fns/registrations/{operation_id}",
                           headers={"X-Kontur-Apikey": APIKEY,
                                    "ExternOidcToken": EXTERN_TOKEN})
        if req.status_code != 200:
            raise HTTPError(f"Unsuccessful HTTP request /fns/registrations/operation_id.\n{req.text}")
        if req.json()['status'] in ("done", "error"):
            print(f"TraceId - {req.headers['X-Kontur-Trace-Id']}")
            return req.json()
        time.sleep(polling_time_sec)


def async_registration_fss_poa(poa_path, signature_path, certificate_path,
                               fss_code="99991", fss_reg_num="9988877766",
                               polling_time_sec=1):
    """Регистрация МЧД для ФСС"""

    organization = get_organization_info(organization_id)["legalEntity"]
    
    def registration_soap_message():
        """Создание SOAP сообщения для регистрации в ФСС"""

        payload ={
             "fssCode": fss_code,
             "fssRegistrationNumber": fss_reg_num,
             "payerInn": organization["inn"],
             "payerKpp": organization["kpp"],
             "payerOgrn": organization["ogrn"],
             # "payerSnils": "25193743483",
             "senderInn": organization["inn"],
             "senderKpp": organization["kpp"],
             "externAccountId": secrets.extern_account_id,
             "senderCertificateContent": base64_encoder(certificate_path, True),
             "senderIpAddress": requests.get("https://api.ipify.org").text
             }
        with open(poa_path, "rb") as poa, open(signature_path, "rb") as sig:
            req = requests.post(f"{URL}/v1/organizations/{organization_id}/operations/fss/soap-messages",
                                headers={"X-Kontur-Apikey": APIKEY,
                                         "ExternOidcToken": EXTERN_TOKEN},
                                data=payload,
                                files={"poa": poa.read(),
                                       "signature": sig.read()})
        if req.status_code != 201:
            raise HTTPError(f"Unsuccessful HTTP request /fss/soap-messages.\n{req.text}")
        print(f"TraceId CREATE SOAP MESSAGE - {req.headers['X-Kontur-Trace-Id']}")
        pprint(req.json())
        return req.json()["id"]

    def get_soap_message_operation(operation_id):
        """Поллинг операции регистрации SOAP сообщения и получение контента"""

        while True:
            req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/fss/soap-messages/{operation_id}",
                               headers={"X-Kontur-Apikey": APIKEY})
            if req.status_code != 200:
                raise HTTPError(f"Unsuccessful HTTP request /soap-messages/operation_id.\n{req.text}")
            if req.json()['status'] == "error":
                return req.json()
            elif req.json()['status'] == "done":
                data = req.json()["result"]
                with open(f"SOAP_fss_{poa_path.split('/')[-1]}.xml", "wb") as soap:
                    req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/fss/soap-messages/{operation_id}/content",
                                       headers={"X-Kontur-Apikey": APIKEY,
                                                "ExternOidcToken": EXTERN_TOKEN})
                    if req.status_code != 200:
                        raise HTTPError(f"Unsuccessful HTTP request /soap-messages/operation_id/content.\n{req.text}")
                    soap.write(req.content)
                    return data
            time.sleep(polling_time_sec)

    def fss_poa_registration(draft_id, document_id):
        """Регистрация МЧД для ФСС"""

        with open(f"SOAP_fss_{poa_path.split('/')[-1]}.xml.sig", "rb") as raw_signature:
            raw_bytes = bytearray(raw_signature.read())
            raw_bytes.reverse()
        payload ={
            "externAccountId": secrets.extern_account_id,
            "draftId": draft_id,
            "documentId": document_id,
            "base64SoapMessageSignature": base64.b64encode(bytes(raw_bytes)).decode(),
            "payerInn": organization["inn"]
            }
        req = requests.post(f"{URL}/v1/organizations/{organization_id}/operations/fss/registrations",
                            headers={"X-Kontur-Apikey": APIKEY,
                                     "ExternOidcToken": EXTERN_TOKEN},
                            json=payload)
        if req.status_code != 201:
            raise HTTPError(f"Unsuccessful HTTP request /fss/registrations.\n{req.text}")
        print(f"TraceId REGISTRATION FSS POA - {req.headers['X-Kontur-Trace-Id']}")
        pprint(req.json())
        operation_id = req.json()["id"]

        while True:
            req = requests.get(f"{URL}/v1/organizations/{organization_id}/operations/fss/registrations/{operation_id}",
                               headers={"X-Kontur-Apikey": APIKEY,
                                        "ExternOidcToken": EXTERN_TOKEN})
            if req.status_code != 200:
                raise HTTPError(f"Unsuccessful HTTP request /fss/registrations/operation_id.\n{req.text}")
            if req.json()['status'] in ("done", "error"):
                return req.json()
            time.sleep(polling_time_sec)

    soap_operation_id = registration_soap_message()
    document_info = get_soap_message_operation(soap_operation_id)
    sign_file(f"SOAP_fss_{poa_path.split('/')[-1]}.xml", True)
    return fss_poa_registration(document_info["draftId"], document_info["documentId"])


###
# Полезное
###


def _get_poa(number, inn, datatype="archive"):
    """Скачивание МЧД по номеру и ИННЮЛ"""

    representative = {"name": "Иван",
                      "surname": "Иванов",
                      "middlename": "Иванович",
                      "snils": "252-639-136 73",
                      "inn": "477704523710"}
    requisites = async_validation({"inn": inn, "kpp": f"{inn[:4]}01001"},
                                  poa_identity={"number": number, "inn": inn},
                                  representative=representative)
    key_mapping = {"representativeInnDoesNotMatch": "inn"}
    try:
        for error in requisites["result"]["errors"]:
            if error['code'] == "representativeInnDoesNotMatch":
                actual_inn = re.findall("'(.*?)'", error['message'])[1]
                break
        return async_download(number, inn, actual_inn, datatype)
    except KeyError:
        return f"KeyError has occured.\n{requisites=}"


def _get_poa_status(number):
    """Запрос статуса МЧД по номеру"""

    if not ENV:
        req = requests.get(f"https://m4d-cprr-it.gnivc.ru/api/v0/poar-portal/public/poa/{number}/public")
    else:
        req = requests.get(f"https://m4d.nalog.gov.ru/api/v0/poar-portal/public/poa/{number}/public")
    if req.status_code != 200:
        raise HTTPError(f"Unsuccessful HTTP request /poa/number/public.\n{req.text}")
    return req.json()["status"]


def _validation_poa_files(poa_path, sign_path):
    """Валидация МЧД по файлам"""

    with open(poa_path, "rb") as xml:
        content = bs4.BeautifulSoup(xml.read(), "xml")
    
    return async_validation({"inn": content.СвРосОрг.attrs["ИННЮЛ"],
                             "kpp": content.СвРосОрг.attrs["КПП"]},
                            poa_files=[poa_path, sign_path],
                            representative={"inn": content.СведФизЛ.attrs["ИННФЛ"],
                                            "snils": content.СведФизЛ.attrs["СНИЛС"],
                                            "name": content.СведФизЛ.ФИО.attrs["Имя"],
                                            "surname": content.СведФизЛ.ФИО.attrs["Фамилия"],
                                            "middlename": content.СведФизЛ.ФИО.attrs["Отчество"]}
                            )
    
if __name__ == "__main__":
    organization_id = set_organization_id(2)
    # poa_identity = {"number": "31cc6eee-b565-4266-9097-2a8ac00ff444", "inn": "4401165141"}
    # principal = {"inn": "4401165141", "kpp": "440101001"}
    # representative = {"name": "Иван", "surname": "Иванов", "snils": "252-639-136 73", "inn": "477704523710"}
