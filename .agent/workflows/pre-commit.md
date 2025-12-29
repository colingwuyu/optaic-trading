---
description: pre-commit code review
---

# Pre-Commit Code Review

1. **Static Analysis**: Run the project's linter and formatter on all staged or modified files.
2. **Security Scan**: Check for hardcoded secrets, API keys, or insecure patterns in the changes.
3. **Test Verification**: Run the full test suite to ensure no regressions were introduced.
4. **Commit Preparation**: 
   - If all checks pass, generate a concise, context-aware commit message based on the implementation plan.
   - If any step fails, stop and present the errors to the user.
