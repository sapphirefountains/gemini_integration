### \#\# 1. System Prerequisites & Dependencies

First, we need to install all the necessary software that Frappe and ERPNext depend on.

1.  **Update Your System:**
    Always start with an up-to-date system.

    ```bash
    sudo apt update && sudo apt upgrade -y
    ```

2.  **Install Core Dependencies:**
    This includes Git (for version control), Python (Frappe v15 requires 3.11+), Redis (for caching & background jobs), and other build tools.

    ```bash
    sudo apt install -y git python3.11-dev python3.11-venv libmysqlclient-dev build-essential redis-server curl libffi-dev
    ```

3.  **Install MariaDB (Database Server):**
    ERPNext uses MariaDB as its database.

    ```bash
    sudo apt install -y mariadb-server mariadb-client
    ```

    After installation, run the secure installation script. It will ask you to set a root password and remove insecure defaults. **Remember the root password you set\!**

    ```bash
    sudo mysql_secure_installation
    ```

    Next, configure MariaDB for Frappe by editing its configuration file.

    ```bash
    sudo nano /etc/mysql/mariadb.conf.d/50-server.cnf
    ```

    Add the following lines under the `[mysqld]` section:

    ```ini
    character-set-server=utf8mb4
    collation-server=utf8mb4_unicode_ci
    ```

    Save the file (`Ctrl+O`, `Enter`) and exit (`Ctrl+X`). Then, restart MariaDB for the changes to take effect.

    ```bash
    sudo systemctl restart mariadb
    ```

4.  **Install Node.js, npm, and Yarn:**
    The Frappe framework uses Node.js for its frontend build processes. Using `nvm` (Node Version Manager) is the recommended way to manage Node versions.

    ```bash
    # Install nvm
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

    # Source your shell configuration to load nvm
    source ~/.bashrc

    # Install and use Node.js v18 (LTS)
    nvm install 18
    nvm use 18

    # Install yarn globally using npm
    npm install -g yarn
    ```

5.  **Install wkhtmltopdf:**
    This is required for printing raw print formats and generating PDFs from the system.

    ```bash
    sudo apt install -y wkhtmltopdf
    ```

-----

### \#\# 2. Install Bench CLI

**Bench** is the command-line interface that helps you install, manage, and update Frappe/ERPNext applications and sites.

```bash
# Install the frappe-bench package using pip
pip3 install frappe-bench

# Verify the installation
bench --version
```

This should output the version of Bench that was installed (e.g., `5.20.0`).

-----

### \#\# 3. Initialize a New Frappe Project

Now, let's create a new project directory (a "bench") that will contain the Frappe framework and all your apps.

1.  **Initialize the Bench Directory:**
    This command will create a new directory named `frappe-bench`, set up a Python virtual environment, and download the Frappe framework. We'll specify `version-15`, which is the current stable version.

    ```bash
    bench init --frappe-branch version-15 frappe-bench
    ```

2.  **Navigate into Your Bench Directory:**
    All subsequent commands must be run from inside this directory.

    ```bash
    cd frappe-bench
    ```

-----

### \#\# 4. Create a New Site & Install ERPNext

A "site" is an instance of an application. You can host multiple sites on a single bench. Given your work at Sapphire Fountains, a good practice is to use a descriptive name.

1.  **Create a New Site:**
    Replace `jules.sapphire.local` with your desired site name. You will be prompted for the MariaDB root password you set earlier and to create a new Administrator password for your ERPNext site. **Save this Administrator password\!**

    ```bash
    bench new-site jules.sapphire.local
    ```

2.  **Download the ERPNext App:**
    Now, get the ERPNext application from its repository. We'll pull `version-15` to match our Frappe framework version.

    ```bash
    bench get-app --branch version-15 erpnext
    ```

3.  **Install the ERPNext App on Your Site:**
    This final step installs the app's database tables and integrates it into your site.

    ```bash
    bench --site jules.sapphire.local install-app erpnext
    ```

-----

### \#\# 5. Start the Development Server

You are now ready to run ERPNext\!

```bash
bench start
```

This command will start the development server. Open your web browser and navigate to **`http://localhost:8000`**. You should see the ERPNext login screen. Log in with the username **Administrator** and the password you created during the `new-site` step.

-----

### \#\# 6. (Recommended) Production Setup

For any real use case beyond local development, you should set up Frappe for production. This configures NGINX as a reverse proxy, and Supervisor to keep the processes running in the background.

First, stop the development server by pressing `Ctrl+C` in the terminal. Then, run the following command. Make sure to replace `[your-linux-user]` with your actual Linux username (e.g., `jules`).

```bash
sudo bench setup production [your-linux-user]
```

After this is complete, you can access your site directly via its domain name (or your server's IP address) without needing to run `bench start`. Bench will automatically configure NGINX to serve your site.

Good luck with your ERPNext implementation\!