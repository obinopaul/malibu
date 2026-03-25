// Initial content for test_1.ts
function greet(name: string, greeting: string = "Hello") {
  return `${greeting}, ${name}!`
}

function farewell(name: string) {
  return `Goodbye, ${name}!`
}

const users = ["Alice", "Bob", "Charlie", "David", "Eve"]
const admins = ["Admin1", "SuperUser"]

for (const user of users) {
  console.log(greet(user))
  console.log(greet(user, "Hi there"))
}

for (const admin of admins) {
  console.log(greet(admin, "Welcome"))
  console.log(farewell(admin))
}

console.log("=== Done processing all users ===")
