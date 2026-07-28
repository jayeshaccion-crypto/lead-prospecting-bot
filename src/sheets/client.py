from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsClient:
    def __init__(self, credentials_json: str, spreadsheet_id: str):
        creds = Credentials.from_service_account_info(
            info=__import__("json").loads(credentials_json),
            scopes=SCOPES,
        )
        self.service = build("sheets", "v4", credentials=creds)
        self.spreadsheet_id = spreadsheet_id

    def tab_exists(self, tab_name: str) -> bool:
        sheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        return any(t["properties"]["title"] == tab_name for t in sheet.get("sheets", []))

    def ensure_tab(self, tab_name: str, headers: list[str]):
        if self.tab_exists(tab_name):
            return
        body = {"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body
        ).execute()
        self.append_rows(tab_name, [headers])

    def read_existing_dedup_keys(self, tab_name: str) -> set[str]:
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=f"'{tab_name}'!K:K")
            .execute()
        )
        values = result.get("values", [])
        keys = set()
        for row in values[1:]:
            if row and row[0].strip():
                keys.add(row[0].strip())
        return keys

    def append_rows(self, tab_name: str, rows: list[list]):
        body = {"values": rows}
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{tab_name}'!A:L",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()

    def get_all_rows(self, tab_name: str) -> list[list]:
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=f"'{tab_name}'!A:L")
            .execute()
        )
        return result.get("values", [])
