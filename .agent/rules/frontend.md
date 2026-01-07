---
trigger: model_decision
description: Agent trigger: Load this file when modifying frontend code (apps/web/).
---

# Frontend Development Rules

Guide for developing features in the React frontend ('apps/web/').

## 1. API Interaction

### Use 'useApiClient' Hook
**Always** use the 'useApiClient' hook to access the API. This ensures the client is properly authenticated with the current session.

\\\	sx
// Correct
import { useApiClient } from '@/services/api';

const MyComponent = () => {
  const api = useApiClient();

  useEffect(() => {
    if (!api) return;
    api.resources.get(id).then(setData);
  }, [api]);
};
\\\`r

### Avoid Raw 'fetch'
**Do NOT** use 'fetch()' directly in components, except for specific edge cases like uploading to a presigned URL where the SDK does not yet provide a helper.

**Why?**
- 'ApiClient' handles auth headers automatically.
- 'ApiClient' provides typed responses.
- 'ApiClient' standardizes error handling.

## 2. Component Structure

- **Functional Components**: Use functional components with hooks.
- **Micro-Components**: Break down complex UIs into smaller, reusable components (e.g., 'ChatPanel', 'ApprovalsPanel').
- **Tailwind CSS**: Use Tailwind for styling. Avoid custom CSS files unless necessary for animations.


## 3. Iterative QA Process

- **Cycle**: Develop -> QA (Browser) -> Report -> Refine.
- **Standards**: UI must be density-rich, modern, and simpler for Quants.
- **Shortcuts**: All primary actions must have keyboard shortcuts.
- **Blind Spots**: If backend lacks features, implement UI as designed and report the gap.