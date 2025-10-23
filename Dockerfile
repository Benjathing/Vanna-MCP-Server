# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for the ODBC driver
# Based on Microsoft's official documentation for Debian
RUN apt-get update && apt-get install -y curl apt-transport-https gnupg

# Add Microsoft's official repository for ODBC
RUN curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /etc/apt/trusted.gpg.d/microsoft.gpg
RUN curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list

# Install the ODBC driver and related tools
# The "accept-eula" is required for silent installation
RUN apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev

# Copy the requirements file and install Python dependencies
COPY requirements.txt .
COPY /odbc.ini / 
RUN odbcinst -i -s -f /odbc.ini -l
RUN cat /etc/odbc.ini
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Make start.sh executable
RUN chmod +x /app/start.sh

# Expose the port the app runs on
EXPOSE 3000

# Define the command to run the application
# This uses the asgi_app object defined in your app.py
CMD ["/app/start.sh"]
