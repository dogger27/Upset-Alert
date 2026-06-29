import client from './client'

export const register = (data) => client.post('/auth/register', data).then(r => r.data)
export const login = (email, password) => {
  const form = new URLSearchParams({ username: email, password })
  return client.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
  }).then(r => r.data)
}
export const getMe = () => client.get('/auth/me').then(r => r.data)
export const updateMe = (data) => client.patch('/auth/me', data).then(r => r.data)
export const listUsers = () => client.get('/auth/users').then(r => r.data)
export const listAdminUsers = () => client.get('/auth/admin/users').then(r => r.data)
export const setUserAdmin = (userId, isAdmin) => client.patch(`/auth/admin/users/${userId}`, { is_admin: isAdmin }).then(r => r.data)
export const getDrawCounts = () => client.get('/auth/users/draw-counts').then(r => r.data)
