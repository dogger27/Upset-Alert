import './UserName.css'

export default function UserName({ user, className = '' }) {
  if (!user?.full_name) {
    return <span className={className}>{user?.display_name}</span>
  }
  return (
    <span
      className={`username-hover ${className}`}
      data-tooltip={user.full_name}
    >
      {user.display_name}
    </span>
  )
}
