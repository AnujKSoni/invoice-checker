import os
import streamlit.components.v1 as components

# Create a _RELEASE flag to switch between dev and production
_RELEASE = True

if not _RELEASE:
    _component_func = components.declare_component(
        "compliance_component",
        url="http://localhost:3001",
    )
else:
    parent_dir = os.path.dirname(os.path.abspath(__file__))
    build_dir = os.path.join(parent_dir, "frontend")
    _component_func = components.declare_component(
        "compliance_component", 
        path=build_dir
    )

def compliance_component(doc_type="GST Invoice", key=None):
    """Create a compliance checker component"""
    component_value = _component_func(
        doc_type=doc_type,
        key=key,
        default=None
    )
    return component_value
