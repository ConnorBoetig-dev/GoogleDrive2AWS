# Secret Handling Guide

## Overview
This project uses Google service account credentials that must be kept secure and never committed to version control.

## Setup Instructions

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

1. `variables.tf` defines a sensitive variable `google_credentials_json`
2. `secrets.auto.tfvars` loads the JSON file content into that variable
3. `main.tf` uses the variable to create the Secrets Manager secret
4. The Lambda function reads from Secrets Manager at runtime

## If You Need to Share the Project

When sharing this project with others:
1. Share the code repository (without secrets)
2. Securely share the `celtic.json` file separately
3. They should place it in `docs/celtic.json`
4. Terraform will work automatically