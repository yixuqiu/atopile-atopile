"""
Find import references.
"""
from typing import Optional, Iterable

from . import datamodel as dm1
from .flat_datamodel import Instance, Joint, make_supers_match_filter, dfs_with_ref
from .datatypes import Ref


def get_ref_from_instance(ref: Ref, instance: Instance) -> Instance:
    """Get a ref from an instance."""
    for ref_part in ref:
        instance = instance.children[ref_part]
    return instance


def build(obj: dm1.Object) -> Instance:
    """Build a flat datamodel."""
    return _build(obj, name="entry")


_IS_A_PIN_OR_SIGNAL = make_supers_match_filter((dm1.PIN, dm1.SIGNAL))


def ref_and_connectable_pairs(instance: Instance) -> Iterable[tuple[Ref, Instance]]:
    """Get all the pins and signals from an instance."""
    return filter(lambda kv: _IS_A_PIN_OR_SIGNAL(kv[1]), dfs_with_ref(instance))


def _build(obj: dm1.Object, name: Optional[str] = None, parent: Optional[Instance] = None, instance: Optional[Instance] = None) -> Instance:
    """Visit an object."""
    if name is not None and parent is not None:
        ref = Ref(parent.ref + (name,))
    else:
        ref = Ref(())

    if instance and obj in instance.origin.supers_bfs:
        # if an instance is already provided, then don't attempt to rewrite existing layers
        # we stop and return the instance here, because we've hit one of the layers we've already built
        return instance
    elif obj.supers_bfs:
        # if there are supers to visit, then visit them first write those higher layers
        instance = _build(obj.supers_bfs[0], name, parent, instance)
    else:
        # if there are no supers to visit, we're at the base layer, and we need to create a new object
        instance = Instance(ref=ref)

    # at this point, we know we're traveling back down the layers
    # we set the origin here, because we want it to point at the last layer applied to this instance
    # it will keep getting overwritten as we travel down the layers
    instance.origin = obj

    # visit all the child objects
    # we do this first, because subsequent operations of creating links, replacements or attributes
    # may override or reference these children
    # it's already been checked that child refs are only one string long
    child_objects = obj.locals_by_type[dm1.Object]
    instance.children_from_classes.update(
        {child_ref[0]: _build(child_obj, name=child_ref[0], parent=instance) for child_ref, child_obj in child_objects}
    )

    # visit replacements after the children are created
    # we make replacements next, because, again, the subsequent operations may
    # reference things from these replacements
    replacements = obj.locals_by_type[dm1.Replace]
    replacements_deepest_first = sorted(replacements, key=lambda x: len(x[1].original_ref))
    for _, replace in replacements_deepest_first:
        assert isinstance(replace, dm1.Replace)
        instance_to_replace = get_ref_from_instance(replace.original_ref, instance)
        _build(
            replace.replacement_obj,
            instance=instance_to_replace
        )

    # visit all the child links
    links = obj.locals_by_type[dm1.Link]
    for _, link in links:
        assert isinstance(link, dm1.Link)
        source_connected = get_ref_from_instance(link.source_ref, instance)
        target_connected = get_ref_from_instance(link.target_ref, instance)

        sources = ref_and_connectable_pairs(source_connected)
        targets = ref_and_connectable_pairs(target_connected)

        for (source_ref, source_instance), (target_ref, target_instance) in zip(sources, targets):
            assert source_ref == target_ref
            joint = Joint(
                link,  # the link that created this joint
                instance,  # the instance that contains this joint
                # the connected objects as spec'd by the user
                source_connected,
                target_connected,
                # the actual objects this link connects
                source_instance,
                target_instance
            )
            source_instance.joined_to_me.append(joint)
            target_instance.joined_to_me.append(joint)
            instance.joints.append(joint)

    # visit all the child params
    # params last, since they might well modify named links in the future
    params = obj.locals_by_type[(str, int)]
    for ref, value in params:
        to_mod = get_ref_from_instance(ref[:-1], instance)
        to_mod.children_from_mods[ref[-1]] = value

    return instance
