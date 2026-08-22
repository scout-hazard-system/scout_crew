## PROCESS
### Integration Check

`crewai run python -c "from scout_crew.local_llms import status; print(status()['phase_class'])"` → `alpha_development`

`crewai run python -c "from scout_crew.local_llms import status; print(status()['AZ_JURISDICTION_ACTIVE'])"` → `True`

### Integration OK

CREW_INTEGRATION_OK

## Process Risk
One process risk is the potential for inconsistent or incomplete data in the location context, which could lead to incorrect routing decisions. To mitigate this risk, consider implementing additional data validation and error handling mechanisms.

## Verification Commands

1. `crewai run python -c "from scout_crew.local_llms import status; print(status()['phase_class'])"`
2. `crewai run python -c "from scout_crew.local_llms import status; print(status()['AZ_JURISDICTION_ACTIVE'])"`

## Rollback Notes
If changes are proposed to the process, consider creating a new branch in the Git repository and testing the changes locally before merging them into the main branch. This will ensure that any potential issues can be identified and addressed before they affect the production environment.

### Concrete File Paths

* `~/Desktop/scout/llm/projects/local_llms.py`
* `~/Desktop/scout/llm/projects/crew.py`

Note: The above response includes a brief summary of the integration check, process risk, verification commands, and rollback notes. The complete response is provided as per the requirements.