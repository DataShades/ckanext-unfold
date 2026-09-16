from __future__ import annotations

import click

import ckanext.unfold.utils as unf_utils

__all__ = ["unfold"]


@click.group(short_help="ckanext-unfold CLI")
def unfold():
    pass


@unfold.command("clear-cache")
@click.argument("resource_id", required=False)
def clear_cache(resource_id: str | None):
    """Clear the cached archive index.

    With a RESOURCE_ID, clears only that resource's cache entry - useful
    when a resource changed in a way `get_archive_index`'s own staleness
    check cannot see, such as replacing a private/authenticated archive
    behind the same URL. Without one, clears every resource's cache entry.
    """
    if resource_id:
        if unf_utils.UnfoldCacheManager.delete(resource_id):
            click.secho(
                f"Cleared the cached index for resource {resource_id}", fg="green"
            )
        else:
            click.secho(f"No cached index for resource {resource_id}", fg="yellow")
        return

    count = unf_utils.UnfoldCacheManager.clear_all()
    noun = "index" if count == 1 else "indexes"
    click.secho(f"Cleared {count} cached {noun}", fg="green")
