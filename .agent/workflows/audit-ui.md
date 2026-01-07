# GUI QA and Audit Workflow

This workflow drives the iterative QA process for frontend features.

1. **Setup**: Ensure local dev server is running (`npm run dev`).
2. **Agent Handover**: Switch to the **`ui-ux-tester`** agent for this workflow.
   - "I am acting as the UI/UX QA Tester to validate [Feature/Page]."

3. **visual_inspection**:
   - Open **Antigravity Browser** to target URL.
   - Verify layout, alignment, and "premium" aesthetic.
   - Capture screenshots of any defects.

4. **functional_verification**:
   - Test primary user flows (clicks, inputs, navigation).
   - Test **Keyboard Shortcuts** (Tab index, Esc, Enter).
   - Verify **backend integration** (loading states, error handling).

5. **report_generation**:
   - Create a QA Report Artifact.
   - Evaluate against "Quant/Scientist" persona needs.
   - List missing backend features/integrations.

6. **iteration**:
   - If critical issues found -> Fix and GOTO Step 3.
   - If pass -> Mark as "UX Approved".

