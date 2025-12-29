"""CLI for guardrails operations."""

import asyncio
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from libs.db.session import AsyncSessionLocal
from optaic.guardrails.runtime.context import GuardrailsContext
from optaic.guardrails.runtime.engine import GuardrailsBlocked, GuardrailsEngine

app = typer.Typer()
console = Console()


@app.command()
def validate(
    resource_id: str = typer.Option(..., help="ID of the resource to validate"),
    action: str = typer.Option(..., help="Action being performed (e.g., update, promote)"),
    tenant_id: str = typer.Option(..., help="Tenant ID"),
    principal_id: str = typer.Option(..., help="Actor Principal ID"),
):
    """Validate an action on a resource against active guardrails."""
    
    async def _run():
        console.print(f"Validating action '{action}' on resource {resource_id}...")
        
        engine = GuardrailsEngine()
        context = GuardrailsContext(
            tenant_id=UUID(tenant_id),
            actor_principal_id=UUID(principal_id),
            action=action,
            space_kind=None, # Populate if known
            subspace_kind=None, # Populate if known
        )
        
        async with AsyncSessionLocal() as db:
            try:
                # For CLI validation, we pass an empty snapshot or we'd need a way to ingest it.
                # Assuming empty means validating the *current state* + no changes?
                # Or simply validating that the *current state* complies?
                # The engine validates `target_snapshot`.
                # Let's pass an empty dict for now as a "dry run" or "check current".
                report = await engine.validate_at_gate(
                    db=db,
                    scope="cli-manual",
                    target_id=resource_id,
                    resource_id=resource_id,
                    context=context,
                    target_snapshot={},
                )
                
                # Commit any report/events
                await db.commit()
                
                table = Table(title=f"Validation Report: {report.report_id}")
                table.add_column("Result", style="cyan")
                table.add_column("Enforced As", style="magenta")
                table.add_column("Issues", style="red")
                
                status = "PASS" if report.ok else "FAIL"
                if not report.ok and report.enforced_as != "block":
                    status = "WARN"
                
                color = "green" if status == "PASS" else "yellow" if status == "WARN" else "red"
                
                table.add_row(
                    f"[{color}]{status}[/{color}]",
                    report.enforced_as,
                    str(len(report.issues))
                )
                console.print(table)
                
                if report.issues:
                    console.print("\n[bold red]Issues:[/bold red]")
                    for i, issue in enumerate(report.issues, 1):
                        console.print(f"{i}. {issue.message} ({issue.code}) at {issue.path}")

            except GuardrailsBlocked as e:
                console.print(f"\n[bold red]BLOCKED: {e}[/bold red]")
                # Blocked means exception raised, but we might want to see the report if possible.
                # The exception has the report_id.
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
