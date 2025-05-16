from fabric import Connection
import argparse

def connect_with_key(host, key_path, user="root"):
    """
    Connects to a remote host via SSH using a private key.

    Args:
        host (str): The hostname or IP address of the remote server.
        key_path (str): The path to the private key file.
        user (str): The username to connect as (default: "root").

    Returns:
        fabric.Connection: A fabric Connection object if successful, None otherwise.
    """
    try:
        c = Connection(
            host=host,
            user=user,
            connect_kwargs={"key_filename": key_path},
        )
        # Test the connection (optional, but recommended)
        c.run("uname -a", hide=True)  # Run a simple command to verify connection
        print(f"Successfully connected to {host} as {user} using key: {key_path}")
        return c
    except Exception as e:
        print(f"Error connecting to {host}: {e}")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Connect to a remote host via SSH using a private key.')
    parser.add_argument('--host', required=True, help='The hostname or IP address of the remote server.')
    parser.add_argument('--key_path', required=True, help='The path to the private key file.')
    parser.add_argument('--user', default='root', help='The username to connect as (default: root).')

    args = parser.parse_args()

    conn = connect_with_key(args.host, args.key_path, args.user)

    if conn:
        # Now you can use the 'conn' object to execute commands on the remote server
        result = conn.run("ls -l /tmp", hide=True)  # Example: List files in /tmp
        print(result.stdout)

        # Close the connection when you're done
        conn.close()
    else:
        print("Failed to establish connection.")