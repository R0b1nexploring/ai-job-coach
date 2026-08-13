import { createContext, useContext } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiRequestError } from '../api/client'
import type { User } from '../types'

type AuthContextValue = { user?: User; loading: boolean; error?: unknown; refresh: () => void }
const AuthContext = createContext<AuthContextValue>({loading:true,refresh:()=>{}})
export function AuthProvider({children}:{children:React.ReactNode}) {
  const client = useQueryClient()
  const query = useQuery({queryKey:['me'],queryFn:()=>api<User>('/api/auth/me'),retry:false})
  const refresh = () => {
    client.removeQueries({ predicate: ({ queryKey }) => queryKey[0] !== 'me' })
    void client.invalidateQueries({ queryKey: ['me'] })
  }
  const unauthorized = query.error instanceof ApiRequestError && query.error.status === 401
  const error = query.error && !unauthorized ? query.error : undefined
  return <AuthContext.Provider value={{user:unauthorized?undefined:query.data,loading:query.isLoading,error,refresh}}>{children}</AuthContext.Provider>
}
export const useAuth = () => useContext(AuthContext)
