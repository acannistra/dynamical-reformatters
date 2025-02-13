import json
import subprocess
from typing import Protocol

from common import docker, kubernetes
from noaa.gefs.forecast.reformat import (
    operational_kubernetes_resources as noaa_gefs_forecast_operational_kubernetes_resources,
)


class OperationalKubernetesResources(Protocol):
    def __call__(self, image_tag: str) -> list[kubernetes.ReformatJob]: ...


OPERATIONAL_RESOURCE_FNS: tuple[OperationalKubernetesResources] = (
    noaa_gefs_forecast_operational_kubernetes_resources,
)


def deploy_operational_updates(
    fns: tuple[OperationalKubernetesResources] = OPERATIONAL_RESOURCE_FNS,
) -> None:
    image_tag = docker.build_and_push_image()

    reformat_jobs: list[kubernetes.ReformatJob] = []
    for fn in fns:
        reformat_jobs.extend(fn(image_tag))

    k8s_resources_str = "\n-----\n".join(
        [
            json.dumps(reformat_job.as_kubernetes_object())
            for reformat_job in reformat_jobs
        ]
    )

    subprocess.run(  # noqa: S603
        ["/usr/bin/kubectl", "apply", "-f", "-"],
        input=k8s_resources_str,
        text=True,
        check=True,
    )
