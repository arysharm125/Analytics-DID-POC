# DID Check

A Vue 3 frontend application for verifying DIDs (Decentralized Identifiers) and Verifiable Credentials.

## Features

- **DID/UID Status Check**: Verify the validity and status of a DID or UID
- **VC Download**: Download Verifiable Credentials associated with a DID
- **Binary Verification**: Verify binary hashes against DID records (hook point)
- **VC Verification**: Client-side verification of Verifiable Credentials (hook point)

## Tech Stack

- Vue 3 (Composition API)
- Vite
- Vuetify 3
- Vue Router
- Pinia (State Management)

## Project Setup

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Project Structure

```
src/
├── components/       # Reusable Vue components
├── composables/      # Vue composables (reusable logic)
│   └── useVerification.js  # Verification hook points
├── plugins/          # Vue plugins configuration
│   └── vuetify.js    # Vuetify configuration
├── router/           # Vue Router configuration
│   └── index.js
├── services/         # API service layer
│   └── api.js        # Backend API calls
├── stores/           # Pinia stores
│   └── did.js        # DID state management
├── views/            # Page components
│   ├── HomeView.vue         # Home page with search
│   └── IdentifierCheck.vue  # DID/UID detail view
├── App.vue           # Root component
└── main.js           # Application entry point
```

## Routes

| Path | Description |
|------|-------------|
| `/` | Home page with search input |
| `/:identifier` | DID/UID detail view (accepts DID strings or UIDs) |

## API Proxy

The Vite dev server proxies `/api/*` requests to the backend:

```js
// vite.config.js
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api/, '')
    }
  }
}
```

For production, configure nginx or your reverse proxy similarly.

## Extending the Application

### Adding Admin Routes

The router is structured to allow easy addition of admin routes:

```js
// router/index.js
import adminRoutes from './adminRoutes'

const routes = [
  // ... existing routes
  {
    path: '/admin',
    component: AdminLayout,
    children: adminRoutes,
    meta: { requiresAuth: true }
  }
]
```

### Implementing Verification

The `useVerification` composable provides hook points for implementing verification logic:

```js
import { useVerification } from '@/composables/useVerification'

const { verifyVC, verifyBinaryHash } = useVerification()

// Implement in useVerification.js:
// - verifyVC(vcData) - Verify VC signatures
// - verifyBinaryHash(binary, expectedHash) - Verify binary hashes
// - verifyDIDDocument(didDocument) - Verify DID document proofs
```

## Environment Variables

Create a `.env.local` file for local configuration:

```env
VITE_API_BASE_URL=http://localhost:8000
```

## License

Proprietary - AMD
