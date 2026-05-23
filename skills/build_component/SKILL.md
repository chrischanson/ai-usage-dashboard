---
name: "Build UI Component"
description: "Generates a clean, beautifully styled, and responsive UI component based on a specification"
default_agent: "agy"
required_vars:
  - COMPONENT_NAME
  - SPECIFICATION
---

# Instructions

You are an expert frontend and design agent. Your task is to build a premium, state-of-the-art UI component matching the user's specification.

## Component Details
* **Component Name:** {COMPONENT_NAME}
* **Specification / Purpose:** {SPECIFICATION}

## Guidelines and Standards
1. **Rich Aesthetics:** Ensure visual excellence. Use highly harmonized color palettes (HSL or elegant dark/light modes), custom typography (like Inter or Roboto), smooth borders, gradients, and micro-interactions.
2. **Structure & Logic:** Use HTML for structure, CSS for styling, and JavaScript for any dynamic logic. Keep it modular and clean.
3. **No Placeholders:** All content must be fully working and demonstrative. Do not leave placeholder sections or empty tags.
4. **File Creation:** Create a dedicated directory under `skills/temp_outputs/` with the component name (e.g. `skills/temp_outputs/{COMPONENT_NAME}/`). Write:
   * `index.html` (the markup, including mock state/inputs)
   * `style.css` (custom design system tokens and layout styles)
   * `app.js` (logic, interactive controls, animations)

## Verification
Ensure the file references between HTML, CSS, and JS are correct and relative. Verify the styling looks high-end before finishing.
