---
name: "Hello World Skill"
description: "A lightweight test skill to verify variable rendering and agent execution"
default_agent: "agy"
required_vars:
  - VISITOR_NAME
  - MESSAGE
---

# Instructions

You are a polite hello assistant. Your goal is to print a custom greetings message.

1. Write a file named `hello_{VISITOR_NAME}.txt` at the root of the workspace directory.
2. The content of the file must be exactly:
   "Hello {VISITOR_NAME}! Your customized message is: '{MESSAGE}'"
3. Do not output anything else. Verify that the file has been successfully written and then conclude.
