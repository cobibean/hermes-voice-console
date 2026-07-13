import {
  ClerkProvider,
  Show,
  SignInButton,
  SignUpButton,
  UserButton,
  useAuth,
} from '@clerk/react';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { DesktopConsole } from './console/DesktopConsole';
import { MobileConsole } from './console/MobileConsole';
import { useConsoleController } from './console/useConsoleController';
import { useConsoleLayout } from './console/useConsoleLayout';
import { loadBootstrap, loadPublicConfig, type AuthTokenProvider } from './lib/api';
import { clearRecovery } from './lib/recovery';
import type { Bootstrap, PublicConfig } from './lib/types';

const noToken: AuthTokenProvider = async () => null;

function StatusScreen({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="shell auth-shell">
      <section className="card auth-card">
        <h1>{title}</h1>
        {children}
      </section>
    </main>
  );
}

function ConsoleRuntime({
  publicConfig,
  getToken,
  accountControl,
}: {
  publicConfig: PublicConfig;
  getToken: AuthTokenProvider;
  accountControl?: ReactNode;
}) {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const layout = useConsoleLayout();
  const controller = useConsoleController({
    authMode: publicConfig.auth_mode,
    getToken,
    bootstrap,
    loadError: loadError ?? undefined,
  });

  useEffect(() => {
    let active = true;
    void loadBootstrap(getToken)
      .then((data) => {
        if (!active) return;
        setBootstrap(data);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setLoadError((error as Error).message);
        setBootstrap(null);
      });
    return () => {
      active = false;
    };
  }, [getToken]);

  if (!bootstrap) {
    return (
      <StatusScreen title="Hermes Voice Console">
        <p>{loadError ?? 'Connecting to the console…'}</p>
      </StatusScreen>
    );
  }

  const warning = publicConfig.auth_mode === 'development' ? (
    <p className="warning development-warning">
      Development authentication is active. This console must remain on loopback.
    </p>
  ) : null;

  return layout === 'desktop' ? (
    <DesktopConsole controller={controller} accountControl={accountControl} notice={warning} />
  ) : (
    <MobileConsole controller={controller} accountControl={accountControl} notice={warning} />
  );
}

function ClerkConsole({ publicConfig }: { publicConfig: PublicConfig }) {
  const { getToken, isSignedIn } = useAuth();
  const tokenProvider = useCallback<AuthTokenProvider>(
    (skipCache = false) => getToken({ skipCache }),
    [getToken],
  );
  useEffect(() => {
    if (isSignedIn === false) clearRecovery();
  }, [isSignedIn]);

  return (
    <>
      <Show when="signed-out">
        <StatusScreen title="Hermes Voice Console">
          <p>Sign in to talk with your authorized Hermes agents.</p>
          <div className="button-row">
            <SignInButton mode="modal">
              <button>Sign in</button>
            </SignInButton>
            <SignUpButton mode="modal">
              <button className="secondary">Create account</button>
            </SignUpButton>
          </div>
        </StatusScreen>
      </Show>
      <Show when="signed-in">
        <ConsoleRuntime
          publicConfig={publicConfig}
          getToken={tokenProvider}
          accountControl={<UserButton />}
        />
      </Show>
    </>
  );
}

export function App() {
  const [publicConfig, setPublicConfig] = useState<PublicConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadPublicConfig()
      .then(setPublicConfig)
      .catch((loadError: unknown) => setError((loadError as Error).message));
  }, []);

  if (!publicConfig) {
    return (
      <StatusScreen title="Hermes Voice Console">
        <p>{error ?? 'Loading console configuration…'}</p>
      </StatusScreen>
    );
  }

  if (publicConfig.auth_mode === 'service') {
    return (
      <StatusScreen title="Programmatic access only">
        <p>This deployment accepts service clients and does not expose a browser sign-in.</p>
      </StatusScreen>
    );
  }

  if (publicConfig.auth_mode === 'development') {
    return <ConsoleRuntime publicConfig={publicConfig} getToken={noToken} />;
  }

  if (!publicConfig.clerk_publishable_key) {
    return (
      <StatusScreen title="Console configuration error">
        <p>Clerk mode is missing its publishable key.</p>
      </StatusScreen>
    );
  }

  return (
    <ClerkProvider publishableKey={publicConfig.clerk_publishable_key}>
      <ClerkConsole publicConfig={publicConfig} />
    </ClerkProvider>
  );
}
