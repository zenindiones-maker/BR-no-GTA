from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable


INSTANCE_TYPES = ("g6f.2xlarge", "g6.2xlarge")
REQUIRED_GPU_VCPUS = 16
REGION = "sa-east-1"
PRICING_REGION = "us-east-1"
AWS_LOCATION = "South America (Sao Paulo)"

PROJECT_SECRET_PARAMETERS = {
    "hazewave": {
        "tailscale": "/cloud-media-workstations/hazewave/tailscale-auth-key",
        "sunshine_username": "/cloud-media-workstations/hazewave/sunshine-username",
        "sunshine_password": "/cloud-media-workstations/hazewave/sunshine-password",
    },
    "br-no-gta": {
        "tailscale": "/cloud-media-workstations/br-no-gta/tailscale-auth-key",
        "sunshine_username": "/cloud-media-workstations/br-no-gta/sunshine-username",
        "sunshine_password": "/cloud-media-workstations/br-no-gta/sunshine-password",
    },
}


class AwsAuthBlocked(RuntimeError):
    pass


class GpuQuotaBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class PreflightConfig:
    region: str
    monthly_budget_usd: float | None


@dataclass(frozen=True)
class PreflightEvidence:
    account_reference: str
    region: str
    gpu_quota_vcpus: float
    required_gpu_vcpus: int
    shared_azs: tuple[str, ...]
    instance_hourly_usd: dict[str, float | None]
    gp3_usd_per_gb_month: float | None
    data_transfer_dimensions: tuple[dict[str, Any], ...]
    secret_parameters: dict[str, dict[str, bool]]
    monthly_budget_usd: float | None
    pricing_source: str
    capacity_evidence: str


@dataclass(frozen=True)
class PreflightEvaluation:
    overall_status: str
    blockers: tuple[str, ...]
    capacity_status: str


def safe_account_reference(account_id: str) -> str:
    digest = hashlib.sha256(str(account_id).encode("utf-8")).hexdigest()
    return "sha256:" + digest[:16]


def account_safe_reference(account_id: str) -> str:
    """Backward-compatible alias used by the CLI receipt."""
    return safe_account_reference(account_id)


def find_gpu_quota(quotas: Iterable[dict[str, Any]]) -> float:
    for row in quotas:
        name = str(row.get("QuotaName") or "")
        if "Running On-Demand G and VT instances" in name:
            return float(row.get("Value") or 0.0)
    raise GpuQuotaBlocked("BLOCKED_GPU_QUOTA:QUOTA_NOT_FOUND")


def shared_instance_azs(offerings: Iterable[dict[str, Any]]) -> list[str]:
    by_type: dict[str, set[str]] = {instance_type: set() for instance_type in INSTANCE_TYPES}
    for row in offerings:
        instance_type = str(row.get("InstanceType") or "")
        location = str(row.get("Location") or "")
        if instance_type in by_type and location:
            by_type[instance_type].add(location)
    if not by_type:
        return []
    values = list(by_type.values())
    common = values[0].copy()
    for value in values[1:]:
        common.intersection_update(value)
    return sorted(common)


def extract_price_dimensions(product: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for term in product.get("terms", {}).get("OnDemand", {}).values():
        for dimension in term.get("priceDimensions", {}).values():
            raw = dimension.get("pricePerUnit", {}).get("USD")
            if raw in (None, ""):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "unit": str(dimension.get("unit") or ""),
                    "description": str(dimension.get("description") or ""),
                    "usd": value,
                }
            )
    return rows


def _quota_value(client: Any) -> tuple[float, str | None]:
    response = client.list_service_quotas(ServiceCode="ec2")
    quotas = response.get("Quotas", [])
    value = find_gpu_quota(quotas)
    code = next(
        (
            row.get("QuotaCode")
            for row in quotas
            if "Running On-Demand G and VT instances" in str(row.get("QuotaName") or "")
        ),
        None,
    )
    return value, code


def _offerings(client: Any, instance_type: str) -> list[dict[str, str]]:
    response = client.describe_instance_type_offerings(
        LocationType="availability-zone",
        Filters=[{"Name": "instance-type", "Values": [instance_type]}],
    )
    return [
        {
            "InstanceType": str(row.get("InstanceType") or instance_type),
            "Location": str(row.get("Location") or ""),
        }
        for row in response.get("InstanceTypeOfferings", [])
        if row.get("Location")
    ]


def _price(products: dict[str, Any], *, unit: str) -> float:
    for raw in products.get("PriceList", []):
        product = json.loads(raw) if isinstance(raw, str) else raw
        for row in extract_price_dimensions(product):
            if row["unit"] == unit:
                return float(row["usd"])
    raise RuntimeError("PRICE_NOT_FOUND:" + unit)


def _price_rows(products: dict[str, Any], *, unit: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in products.get("PriceList", []):
        product = json.loads(raw) if isinstance(raw, str) else raw
        for row in extract_price_dimensions(product):
            if unit is None or row["unit"] == unit:
                rows.append(row)
    return rows


def _pricing_filters(**terms: str) -> list[dict[str, str]]:
    return [
        {"Type": "TERM_MATCH", "Field": field, "Value": value}
        for field, value in terms.items()
    ]


def _compute_price(pricing: Any, instance_type: str) -> float:
    products = pricing.get_products(
        ServiceCode="AmazonEC2",
        Filters=_pricing_filters(
            location=AWS_LOCATION,
            instanceType=instance_type,
            operatingSystem="Linux",
            tenancy="Shared",
            preInstalledSw="NA",
            capacitystatus="Used",
        ),
        MaxResults=100,
    )
    return _price(products, unit="Hrs")


def _gp3_price(pricing: Any) -> float:
    products = pricing.get_products(
        ServiceCode="AmazonEC2",
        Filters=_pricing_filters(
            location=AWS_LOCATION,
            volumeApiName="gp3",
            productFamily="Storage",
        ),
        MaxResults=100,
    )
    return _price(products, unit="GB-Mo")


def _egress_dimensions(pricing: Any) -> list[dict[str, Any]]:
    queries = (
        ("AWSDataTransfer", {"fromLocation": AWS_LOCATION, "transferType": "AWS Out"}),
        ("AmazonEC2", {"fromLocation": AWS_LOCATION, "productFamily": "Data Transfer"}),
    )
    for service_code, terms in queries:
        try:
            products = pricing.get_products(
                ServiceCode=service_code,
                Filters=_pricing_filters(**terms),
                MaxResults=100,
            )
            rows = _price_rows(products, unit="GB")
            if rows:
                return rows
        except Exception:
            continue
    return []


def _parameter_exists(ssm: Any, name: str) -> bool:
    response = ssm.describe_parameters(
        ParameterFilters=[{"Key": "Name", "Option": "Equals", "Values": [name]}],
        MaxResults=10,
    )
    return any(str(row.get("Name") or "") == name for row in response.get("Parameters", []))


def _secret_parameter_evidence(ssm: Any) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    for project, names in PROJECT_SECRET_PARAMETERS.items():
        result[project] = {
            key: _parameter_exists(ssm, name)
            for key, name in names.items()
        }
    return result


def evaluate_preflight(evidence: PreflightEvidence) -> PreflightEvaluation:
    blockers: list[str] = []

    if evidence.gpu_quota_vcpus < evidence.required_gpu_vcpus:
        blockers.append(
            f"GPU_QUOTA_VCPUS_INSUFFICIENT:{evidence.gpu_quota_vcpus:g}"
            f"<{evidence.required_gpu_vcpus}"
        )

    if not evidence.shared_azs:
        blockers.append("NO_SHARED_AZ_OFFERING")

    if (
        any(value is None for value in evidence.instance_hourly_usd.values())
        or evidence.gp3_usd_per_gb_month is None
        or not evidence.data_transfer_dimensions
    ):
        blockers.append("AWS_PRICE_EVIDENCE_INCOMPLETE")

    for project, secrets in evidence.secret_parameters.items():
        for secret_name, present in secrets.items():
            if not present:
                blockers.append(f"SECRET_MISSING:{project}:{secret_name}")

    if evidence.monthly_budget_usd is None:
        blockers.append("MONTHLY_BUDGET_USD_UNSET")

    if any(item.startswith("GPU_QUOTA") for item in blockers):
        status = "BLOCKED_GPU_QUOTA"
    elif "NO_SHARED_AZ_OFFERING" in blockers:
        status = "BLOCKED_CAPACITY"
    elif "AWS_PRICE_EVIDENCE_INCOMPLETE" in blockers:
        status = "BLOCKED_PRICE_EVIDENCE"
    elif any(item.startswith("SECRET_MISSING") for item in blockers):
        status = "BLOCKED_STREAMING"
    elif "MONTHLY_BUDGET_USD_UNSET" in blockers:
        status = "BLOCKED_BUDGET_POLICY"
    else:
        status = "PREFLIGHT_READY_FOR_PROVISIONING"

    return PreflightEvaluation(
        overall_status=status,
        blockers=tuple(blockers),
        capacity_status="UNPROVEN_UNTIL_RUN_INSTANCES",
    )


def run_preflight(*, clients: Any, config: PreflightConfig) -> dict[str, Any]:
    if config.region != REGION:
        raise ValueError("REGION_MUST_BE_SA_EAST_1")

    try:
        identity = clients.sts.get_caller_identity()
    except Exception as exc:
        raise AwsAuthBlocked("BLOCKED_AWS_AUTH") from exc

    available_vcpus, quota_code = _quota_value(clients.quotas)

    offering_rows: list[dict[str, str]] = []
    instance_offerings: dict[str, list[str]] = {}
    for instance_type in INSTANCE_TYPES:
        rows = _offerings(clients.ec2, instance_type)
        offering_rows.extend(rows)
        instance_offerings[instance_type] = sorted(
            {row["Location"] for row in rows if row["Location"]}
        )
    common_azs = shared_instance_azs(offering_rows)

    compute: dict[str, float | None] = {}
    for instance_type in INSTANCE_TYPES:
        try:
            compute[instance_type] = _compute_price(clients.pricing, instance_type)
        except Exception:
            compute[instance_type] = None

    try:
        gp3 = _gp3_price(clients.pricing)
    except Exception:
        gp3 = None

    egress_rows = tuple(_egress_dimensions(clients.pricing))

    ssm = getattr(clients, "ssm", None)
    if ssm is None:
        secrets = {
            project: {key: False for key in names}
            for project, names in PROJECT_SECRET_PARAMETERS.items()
        }
    else:
        secrets = _secret_parameter_evidence(ssm)

    evidence = PreflightEvidence(
        account_reference=safe_account_reference(identity.get("Account", "")),
        region=config.region,
        gpu_quota_vcpus=available_vcpus,
        required_gpu_vcpus=REQUIRED_GPU_VCPUS,
        shared_azs=tuple(common_azs),
        instance_hourly_usd=compute,
        gp3_usd_per_gb_month=gp3,
        data_transfer_dimensions=egress_rows,
        secret_parameters=secrets,
        monthly_budget_usd=config.monthly_budget_usd,
        pricing_source="AWS_PRICE_LIST_API",
        capacity_evidence="INSTANCE_TYPE_OFFERING_ONLY",
    )
    evaluation = evaluate_preflight(evidence)

    return {
        "schema": "CloudMediaWorkstationPreflight/v2",
        "status": evaluation.overall_status,
        "blockers": list(evaluation.blockers),
        "region": config.region,
        "account_safe_reference": evidence.account_reference,
        "gpu_quota": {
            "quota_name": "Running On-Demand G and VT instances",
            "quota_code": quota_code,
            "required_vcpus": REQUIRED_GPU_VCPUS,
            "available_vcpus": available_vcpus,
        },
        "instance_offerings": instance_offerings,
        "shared_azs": list(evidence.shared_azs),
        "capacity": {
            "offering_api": "PASS" if common_azs else "FAIL",
            "actual_capacity": evaluation.capacity_status,
        },
        "cost_evidence": {
            "source": evidence.pricing_source,
            "compute_usd_per_hour": evidence.instance_hourly_usd,
            "ebs_gp3_usd_per_gb_month": evidence.gp3_usd_per_gb_month,
            "data_transfer": list(evidence.data_transfer_dimensions),
        },
        "secret_parameters": evidence.secret_parameters,
        "monthly_budget_usd": evidence.monthly_budget_usd,
        "monthly_budget_status": (
            "SET" if evidence.monthly_budget_usd is not None else "MONTHLY_BUDGET_USD_UNSET"
        ),
        "unattended_start_allowed": evaluation.overall_status == "PREFLIGHT_READY_FOR_PROVISIONING",
    }
