# Secret Handling Guide

## Overview
This project uses Google service account credentials that must be kept secure and never committed to version control.

## Setup Instructions

### For AWS Console Deployment

1. **Keep your credentials file secure**
   - Store your Google service account JSON file (e.g., `celtic.json`) in a secure location
   - Never commit this file to version control
   - This file contains sensitive authentication credentials

2. **Upload to AWS Secrets Manager via Console**
   - Navigate to **AWS Secrets Manager** → **Store a new secret**
   - Select "Other type of secret" → "Plaintext"
   - Copy and paste the entire contents of your JSON file
   - Name your secret (e.g., `gdrive-backup-credentials`)
   - The Lambda function will securely retrieve credentials at runtime

### For Terraform Deployment (Alternative)

1. **Keep your credentials file**
   - Store `celtic.json` in the `docs/` folder (it's gitignored)
   - This file contains your Google service account credentials

2. **Terraform will automatically use the credentials**
   - The `terraform/secrets.auto.tfvars` file references the credentials
   - Terraform reads the JSON file when you run `terraform apply`

3. **File Structure**
   ```
   GoogleDrive2AWS/
   ├── docs/
   │   └── celtic.json          # Your actual credentials (gitignored)
   ├── terraform/
   │   ├── main.tf
   │   ├── variables.tf
   │   ├── outputs.tf
   │   ├── terraform.tfvars
   │   └── secrets.auto.tfvars  # References the credentials file (gitignored)
   ```

## Important Security Notes

- ✅ `celtic.json` is gitignored and won't be committed
- ✅ `secrets.auto.tfvars` is gitignored and won't be committed  
- ✅ Terraform will use the credentials without exposing them in code
- ❌ Never remove these files from .gitignore
- ❌ Never commit credentials directly in Terraform files

## How It Works

### AWS Console Method
1. You manually upload the Google service account JSON to AWS Secrets Manager
2. The Lambda function is configured with the secret name as an environment variable
3. At runtime, Lambda retrieves the credentials from Secrets Manager
4. Credentials are never exposed in code or logs

### Terraform Method
1. `variables.tf` defines a sensitive variable `google_credentials_json`
2. `secrets.auto.tfvars` loads the JSON file content into that variable
3. `main.tf` uses the variable to create the Secrets Manager secret
4. The Lambda function reads from Secrets Manager at runtime

## If You Need to Share the Project

When sharing this project with others:

### For AWS Console Users
1. Share the code repository (without secrets)
2. Securely share the Google service account JSON file separately
3. They should upload it to their AWS Secrets Manager
4. Update Lambda environment variables with their secret name

### For Terraform Users
1. Share the code repository (without secrets)
2. Securely share the `celtic.json` file separately
3. They should place it in `docs/celtic.json`
4. Terraform will work automatically