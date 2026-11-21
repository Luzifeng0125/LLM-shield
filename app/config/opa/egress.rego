package shield.egress

import rego.v1

default allow := false

# Example organization policy. Replace these grants with approved workflows.
grants := {
    ["student_leader", "meeting_minutes", "external_model", "model_input"],
    ["student_leader", "meeting_minutes", "external_model", "chat_output"],
    ["student_leader", "meeting_minutes", "viewer_peer", "view_display"],
    ["student_leader", "meeting_minutes", "egress_tool_internal", "tool_egress"],
}

allow if {
    [input.identity, input.task, input.recipient, input.operation] in grants
}
