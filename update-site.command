#!/bin/bash
# Double-click this file to update the Suffolk Village Signs website.

# Change to project directory
cd "$(dirname "$0")"

# Activate Python environment
source .venv/bin/activate

# Run build script
echo "Building site from photos..."
python scripts/build.py
if [ $? -ne 0 ]; then
  echo ""
  echo "Build failed. See error above."
  read -p "Press Return to close..."
  exit 1
fi

# Commit and push
git add docs/
git commit -m "Update site with new photos"
git push

echo ""
echo "Done! Your site will update within a minute."
echo "https://dermotor-md.github.io/suffolk-village-signs/"
echo ""
read -p "Press Return to close..."
