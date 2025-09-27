import frappe

def setup_test_data():
    """Sets up test data for manual testing."""
    # Create a test customer
    if not frappe.db.exists("Customer", "Test Customer"):
        frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "Test Customer",
            "customer_type": "Individual"
        }).insert()

    # Create a test project
    if not frappe.db.exists("Project", "Test Project"):
        frappe.get_doc({
            "doctype": "Project",
            "project_name": "Test Project",
            "status": "Open"
        }).insert()

    # Create a test task
    if not frappe.db.exists("Task", "Test Task"):
        frappe.get_doc({
            "doctype": "Task",
            "subject": "Test Task",
            "status": "Open",
            "project": "Test Project"
        }).insert()

    frappe.db.commit()
    print("Test data set up successfully.")

if __name__ == "__main__":
    setup_test_data()