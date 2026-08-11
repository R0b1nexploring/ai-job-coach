import { createContext, useContext } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { User } from '../types'

const AuthContext = createContext<{user?:User; loading:boolean; refresh:()=>void}>({loading:true,refresh:()=>{}})
export function AuthProvider({children}:{children:React.ReactNode}) {
  const client = useQueryClient()
  const query = useQuery({queryKey:['me'],queryFn:()=>api<User>('/api/auth/me'),retry:false})
  const refresh = () => {
    client.removeQueries({ predicate: ({ queryKey }) => queryKey[0] !== 'me' })
    void client.invalidateQueries({ queryKey: ['me'] })
  }
  return <AuthContext.Provider value={{user:query.data,loading:query.isLoading,refresh}}>{children}</AuthContext.Provider>
}
export const useAuth = () => useContext(AuthContext)
