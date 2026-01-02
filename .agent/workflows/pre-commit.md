---
description: pre-commit code review
---

# Pre-Commit Code Review

1. **Static Analysis**: Run the project's linter and formatter on all staged or modified files.
2. **Security Scan**: Check for hardcoded secrets, API keys, or insecure patterns in the changes.
3. **Test Verification**: Run the full test suite to ensure no regressions were introduced.
4. **Documentation Check**: Review and update `README.md` and `docs/` to reflect changes. Ensure documentation specifically addresses:
   - **DevOps**: Deployment, artifactory, and infrastructure changes.
   - **System Dev**: Code architecture, dependencies, and testing patterns.
   - **Frontend Dev**: API changes, component usage, and UI patterns.
   - **Quant/Data**: SDK extensions, new models, and GUI features.
5. **Commit Preparation**: 
   - If all checks pass, generate a concise, context-aware commit message based on the implementation plan.
   - If any step fails, stop and present the errors to the user.
