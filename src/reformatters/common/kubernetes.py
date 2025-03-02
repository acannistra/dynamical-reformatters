import random
import string
from collections.abc import Sequence
from datetime import timedelta
from typing import Annotated, Any

import pydantic


class Job(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    command: Annotated[Sequence[str], pydantic.Field(min_length=1)]
    image: Annotated[str, pydantic.Field(min_length=1)]
    dataset_id: Annotated[str, pydantic.Field(min_length=1)]
    cpu: Annotated[str, pydantic.Field(min_length=1)]
    memory: Annotated[str, pydantic.Field(min_length=1)]
    ephemeral_storage: Annotated[str, pydantic.Field(min_length=1)] = "10G"
    workers_total: Annotated[int, pydantic.Field(ge=1)]
    parallelism: Annotated[int, pydantic.Field(ge=1)]
    ttl: timedelta = timedelta(days=1)

    @property
    def job_name(self) -> str:
        # Job names should be a valid DNS name, 63 characters or less
        name = f"{self.dataset_id[:21]}-{'-'.join(self.command)}"
        name = name.lower().replace("_", "-").replace(":", "-")
        name = name[:52]  # we add 5 random, then pods within the job add 6. 52+5+6=63
        random_chars = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=4)  # noqa: S311
        )
        return f"{name}-{random_chars}"

    def as_kubernetes_object(self) -> dict[str, Any]:
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": self.job_name},
            "spec": {
                "backoffLimitPerIndex": 5,
                "completionMode": "Indexed",
                "completions": self.workers_total,
                "maxFailedIndexes": min(100, max(5, self.workers_total // 8)),
                "parallelism": self.parallelism,
                "podFailurePolicy": {
                    "rules": [
                        {
                            "action": "Ignore",
                            "onPodConditions": [
                                {"type": "DisruptionTarget", "status": "True"}
                            ],
                        },
                        {
                            "action": "FailJob",
                            "onPodConditions": [
                                {"type": "ConfigIssue", "status": "True"}
                            ],
                        },
                    ]
                },
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "command": [
                                    "python",
                                    "src/reformatters/__main__.py",
                                    f"{self.dataset_id}",
                                    *self.command,
                                ],
                                "env": [
                                    {"name": "DYNAMICAL_ENV", "value": "prod"},
                                    {
                                        "name": "DYNAMICAL_SENTRY_DSN",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "key": "DYNAMICAL_SENTRY_DSN",
                                                "name": "sentry",
                                            }
                                        },
                                    },
                                    {
                                        "name": "WORKER_INDEX",
                                        "valueFrom": {
                                            "fieldRef": {
                                                "fieldPath": "metadata.annotations['batch.kubernetes.io/job-completion-index']"
                                            }
                                        },
                                    },
                                    {
                                        "name": "WORKERS_TOTAL",
                                        "value": f"{self.workers_total}",
                                    },
                                    {
                                        "name": "DYNAMICAL_SOURCE_COOP_AWS_ACCESS_KEY_ID",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "key": "AWS_ACCESS_KEY_ID",
                                                "name": "source-coop-key",
                                            }
                                        },
                                    },
                                    {
                                        "name": "DYNAMICAL_SOURCE_COOP_AWS_SECRET_ACCESS_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "key": "AWS_SECRET_ACCESS_KEY",
                                                "name": "source-coop-key",
                                            }
                                        },
                                    },
                                ],
                                "image": f"{self.image}",
                                "name": "worker",
                                "resources": {
                                    "requests": {
                                        "cpu": f"{self.cpu}",
                                        "memory": f"{self.memory}",
                                    }
                                },
                                "volumeMounts": [
                                    {"mountPath": "/app/data", "name": "ephemeral-vol"},
                                    {
                                        "mountPath": "/dev/shm",  # noqa: S108 yes we're using a known, shared path
                                        "name": "shared-memory-dir",
                                    },
                                ],
                            }
                        ],
                        "nodeSelector": {
                            "eks.amazonaws.com/compute-type": "auto",
                            "karpenter.sh/capacity-type": "spot",
                        },
                        "restartPolicy": "Never",
                        "securityContext": {
                            "fsGroup": 999,  # this is the `app` group our app runs under
                        },
                        "terminationGracePeriodSeconds": 5,
                        "volumes": [
                            {
                                "ephemeral": {
                                    "volumeClaimTemplate": {
                                        "metadata": {"labels": {"type": "ephemeral"}},
                                        "spec": {
                                            "accessModes": ["ReadWriteOnce"],
                                            "resources": {
                                                "requests": {
                                                    "storage": f"{self.ephemeral_storage}"
                                                }
                                            },
                                        },
                                    }
                                },
                                "name": "ephemeral-vol",
                            },
                            {
                                "name": "shared-memory-dir",
                                "emptyDir": {"medium": "Memory", "sizeLimit": "22Gi"},
                            },
                        ],
                    }
                },
                "ttlSecondsAfterFinished": int(self.ttl.total_seconds()),
            },
        }


class CronJob(Job):
    name: Annotated[str, pydantic.Field(min_length=1)]
    schedule: Annotated[str, pydantic.Field(min_length=1)]
    ttl: timedelta = timedelta(hours=12)
    suspend: bool = False

    def as_kubernetes_object(self) -> dict[str, Any]:
        job_spec = super().as_kubernetes_object()["spec"]
        return {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {"name": self.name},
            "spec": {
                "schedule": self.schedule,
                "suspend": self.suspend,
                "concurrencyPolicy": "Replace",
                "jobTemplate": {"spec": job_spec},
            },
        }


class ReformatCronJob(CronJob):
    command: Sequence[str] = ["reformat-operational-update"]
    # Operational updates expect a single worker
    workers_total: int = 1
    parallelism: int = 1


class ValidationCronJob(CronJob):
    command: Sequence[str] = ["validate-zarr"]
    workers_total: int = 1
    parallelism: int = 1
