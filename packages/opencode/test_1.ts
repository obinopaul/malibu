// Initial test file for demonstrating edit and multiedit tools
// This is a simple TypeScript test file

const greeting = "Hello, Universe!"
const version = "2.0.0"
const author = "Demo User"

function main() {
  console.log(greeting)
  console.log("Version:", version)
  console.log("Author:", author)
}

interface Config {
  name: string
  value: number
}

const defaultConfig: Config = {
  name: "production",
  value: 100,
}

main()
