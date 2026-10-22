import React, { createContext, useContext, useEffect, useState } from "react";
import {
  AuthUser,
  getCurrentUser,
  isTokenValid,
  signIn as cognitoSignIn,
  signUp as cognitoSignUp,
  confirmSignUp as cognitoConfirmSignUp,
  signOut as cognitoSignOut,
  refreshSession,
} from "@/lib/auth";

export interface AuthContextType {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  signIn: (email: string, pass: string) => Promise<AuthUser>;
  signUp: (email: string, pass: string, name: string) => Promise<any>;
  confirmSignUp: (email: string, code: string) => Promise<any>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    const initAuth = async () => {
      try {
        if (isTokenValid()) {
          const currentUser = getCurrentUser();
          setUser(currentUser);
        } else {
          // Attempt refresh
          const refreshed = await refreshSession();
          if (refreshed) {
            setUser(getCurrentUser());
          } else {
            setUser(null);
          }
        }
      } catch (err) {
        console.error("Auth initialization error:", err);
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    };

    initAuth();
  }, []);

  const handleSignIn = async (email: string, pass: string): Promise<AuthUser> => {
    setIsLoading(true);
    try {
      const loggedUser = await cognitoSignIn(email, pass);
      setUser(loggedUser);
      return loggedUser;
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignUp = async (email: string, pass: string, name: string) => {
    return await cognitoSignUp(email, pass, name);
  };

  const handleConfirmSignUp = async (email: string, code: string) => {
    return await cognitoConfirmSignUp(email, code);
  };

  const handleSignOut = () => {
    cognitoSignOut();
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        signIn: handleSignIn,
        signUp: handleSignUp,
        confirmSignUp: handleConfirmSignUp,
        signOut: handleSignOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuthContext = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuthContext must be used within an AuthProvider");
  }
  return context;
};
