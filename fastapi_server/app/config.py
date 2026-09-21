# Copyright 2026 DataRobot, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json
import os
from typing import Any, Sequence

from datarobot.core.config import DataRobotAppFrameworkBaseSettings
from pydantic import Field, ValidationInfo, field_validator

from app.auth.oauth import OAuthImpl
from app.telemetry.enums import FormatType, LogLevel


class Config(DataRobotAppFrameworkBaseSettings):
    session_secret_key: str

    datarobot_endpoint: str
    datarobot_api_token: str

    session_max_age: int = 14 * 24 * 60 * 60  # 14 days, in seconds
    session_https_only: bool = True
    session_cookie_name: str = "sess"  # Can be overridden for different apps

    log_level: LogLevel = LogLevel.INFO
    log_format: FormatType = "text"

    agent_port: int = Field(default=8842, ge=1, le=65535)
    agent_endpoint: str | None = None

    @field_validator("agent_port", mode="before")
    @classmethod
    def ignore_agent_port_when_deployed(cls, v: object) -> object:
        # AGENT_PORT only matters for local development, where it is the fallback
        # used to build agent_endpoint (see set_agent_endpoint below). When
        # deployed, AGENT_ENDPOINT is set explicitly and agent_port is never read,
        # so the two are effectively mutually exclusive.
        #
        # Skip AGENT_PORT entirely (keep the default) whenever AGENT_ENDPOINT is
        # set. Besides matching that intent, this avoids a startup crash in shared
        # Kubernetes namespaces that contain a Service named "agent": the kubelet
        # injects a service-link env var AGENT_PORT=tcp://<clusterIP>:<port>, which
        # is not a valid int and would otherwise fail Config validation.
        if os.getenv("AGENT_ENDPOINT"):
            return 8842  # Config-level default; unused when deployed
        return v

    @field_validator("agent_endpoint", mode="before")
    @classmethod
    def set_agent_endpoint(cls, v: str | None, info: ValidationInfo) -> str:
        # For local development agent_port is set. When deployed via pulumi, the agent_endpoint is
        # set
        if v is not None and v != "":
            return v
        agent_port = info.data.get("agent_port", 8842)
        return f"http://localhost:{agent_port}"

    oauth_impl: OAuthImpl | None = None

    @field_validator("oauth_impl", mode="before")
    @classmethod
    def set_oauth_impl(cls, v: str | OAuthImpl | None) -> str | OAuthImpl:
        # Either read via runtime parameters, or infer from infra for local development
        if v is not None and v != "":
            return v
        if OAuthImpl.AUTHLIB in os.getenv("INFRA_ENABLE_OAUTH", ""):
            return OAuthImpl.AUTHLIB
        return OAuthImpl.DATAROBOT

    datarobot_oauth_providers: Sequence[str] = ()

    google_client_id: str | None = None
    google_client_secret: str | None = None

    box_client_id: str | None = None
    box_client_secret: str | None = None

    microsoft_client_id: str | None = None
    microsoft_client_secret: str | None = None

    # these two configs should help to emulate the DataRobot Custom App Authentication like in a deployment application but locally,
    # so you can assume the user and be able to open the UI in the browser without any other configurations.
    # If both are set at the same time, only the DR API key will be used to authenticate the user.
    test_user_api_key: str | None = None
    test_user_email: str | None = None

    database_uri: str = "sqlite+aiosqlite:///.data/database.sqlite"

    # Clinical Data Integrity Agent — Snowflake connection for the review UI.
    # The backend reads flagged encounters and the audit trail, and persists
    # approvals, directly against the system of record. The PAT arrives the same
    # way as any other secret (Shared Secure Configuration -> SNOWFLAKE_PAT env).
    snowflake_pat: str | None = None
    snowflake_account: str = "hyjszhg-ex34549"
    snowflake_user: str | None = None
    snowflake_warehouse: str = "DEMO_WH"
    snowflake_database: str = "CSE_DEMO"
    snowflake_schema: str = "WORKSHOP"
    snowflake_role: str | None = None
    use_local_sqlite: bool = False
    local_sqlite_path: str = "demo.db"

    @field_validator("snowflake_pat", mode="before")
    @classmethod
    def _extract_snowflake_pat(cls, v: Any) -> Any:
        """Normalize the PAT from a DataRobot credential to the raw token string.

        A credential-type runtime parameter may arrive as the token string, or as
        a dict / JSON string with one of several keys (apiToken / api_token /
        password / value). Extract the token regardless of shape.
        """
        if v is None:
            return v
        data = v
        if isinstance(data, str):
            text = data.strip()
            if text.startswith("{"):
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    return text  # plain token that happens to start with '{'? keep it
            else:
                return text
        if isinstance(data, dict):
            for key in ("apiToken", "api_token", "password", "value", "token"):
                if data.get(key):
                    return str(data[key])
            return None
        return v

    # LLM for the read-only "ask about this encounter" chat. The backend calls the
    # DataRobot LLM Gateway directly (OpenAI-compatible) with the same model the
    # agent uses. This path exposes no tools, so it is structurally read-only —
    # it can never write back a correction.
    llm_default_model: str = "datarobot/anthropic/claude-sonnet-4-6"
    llm_use_datarobot_llm_gateway: bool = True

    use_application_memory_space: bool = Field(
        default=False, validation_alias="USE_APPLICATION_MEMORY_SPACE"
    )
    application_memory_space_id: str | None = Field(
        default=None, validation_alias="APPLICATION_MEMORY_SPACE_ID"
    )

    # The number of characters to stream before persisting
    minimal_chunks_to_persist: int = 5000

    profiling_enabled: bool = False

    application_id: str | None = None

    otel_entity_id: str = ""
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_sdk_disabled: bool = False

    @field_validator("otel_exporter_otlp_headers", mode="before")
    @classmethod
    def _assemble_otel_headers(cls, v: object, info: ValidationInfo) -> object:
        if v:
            return v
        entity_id = (info.data or {}).get("otel_entity_id", "")
        api_token = (info.data or {}).get("datarobot_api_token", "") or os.environ.get(
            "DATAROBOT_API_TOKEN", ""
        )
        if entity_id and api_token:
            return f"x-datarobot-entity-id={entity_id},x-datarobot-api-key={api_token}"
        return v

    @field_validator("otel_sdk_disabled", mode="before")
    @classmethod
    def _coerce_empty_string(cls, v: object) -> object:
        return False if v == "" else v

    @property
    def application_endpoint(self) -> str:
        """Construct the application endpoint URL"""
        if not self.application_id:
            port = os.getenv("PORT", "8080")
            return f"http://localhost:{port}/api/v1"

        base_url = self.datarobot_endpoint.rstrip("/").removesuffix("/api/v2")
        return f"{base_url}/custom_applications/{self.application_id}/api/v1"
