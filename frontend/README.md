# CareerOps Frontend

React and TypeScript frontend for the AI Internship Application Assistant.

```bash
cd frontend
npm install
npm run dev
```

The backend defaults to `http://localhost:8000`. Override it in `.env` with
`VITE_API_BASE_URL`. Run checks with `npm run build` and `npm test`.

Tests mock API calls and require no live providers. This frontend is intended
for trusted local development until authentication and user isolation exist.
API responses remain in React Query memory and are not written to local
storage.
