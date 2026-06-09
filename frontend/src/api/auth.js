import client from './client'

export const register = (data) => client.post('/auth/register', data).then(r => r.data)
export const login = (email, password) => {
  const form = new URLSearchParams({ username: email, password })
  return client.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
  }).then(r => r.data)
}
export const getMe = () => client.get('/auth/me').then(r => r.data)
