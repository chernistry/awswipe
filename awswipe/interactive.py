"""Interactive TUI for AWSwipe using Textual."""
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer, Button, Static, SelectionList, Input
from textual.widgets.selection_list import Selection
from textual.screen import Screen
from textual.binding import Binding
from textual import on, work

from awswipe.core.config import Config
from awswipe.core.logging import setup_logging, get_run_id
from awswipe.cleaner import SuperAWSResourceCleaner


class ConfirmScreen(Screen):
    """Confirmation dialog screen."""
    
    BINDINGS = [("escape", "cancel", "Cancel")]
    
    def __init__(self, message: str, callback, danger: bool = True):
        super().__init__()
        self.message = message
        self.callback = callback
        self.danger = danger
    
    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            yield Static(f"⚠️  {self.message}", id="confirm-message")
            if self.danger:
                yield Input(placeholder="Type CONFIRM to proceed", id="confirm-input")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Proceed", variant="error", id="proceed")
    
    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.app.pop_screen()
    
    @on(Button.Pressed, "#proceed")
    def proceed(self) -> None:
        if self.danger:
            inp = self.query_one("#confirm-input", Input)
            if inp.value != "CONFIRM":
                inp.value = ""
                inp.placeholder = "Type CONFIRM!"
                return
        self.app.pop_screen()
        self.callback()
    
    def action_cancel(self) -> None:
        self.app.pop_screen()


class ResourceSelectScreen(Screen):
    """Resource type selection screen."""
    
    BINDINGS = [("escape", "cancel", "Cancel")]
    
    RESOURCES = [
        ("ec2", "EC2 Instances"),
        ("ebs", "EBS Volumes & Snapshots"),
        ("s3", "S3 Buckets"),
        ("lambda", "Lambda Functions"),
        ("vpc", "VPC & Networking"),
        ("iam", "IAM Roles"),
        ("rds", "RDS Databases"),
        ("eks", "EKS Clusters"),
        ("elb", "Load Balancers"),
        ("route53", "Route53"),
    ]
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
    
    def compose(self) -> ComposeResult:
        with Container(id="select-dialog"):
            yield Static("Select resource types:", id="select-title")
            yield SelectionList[str](
                *[Selection(name, value, True) for value, name in self.RESOURCES],
                id="resource-list"
            )
            with Horizontal(id="select-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Continue", variant="primary", id="continue")
    
    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.app.pop_screen()
    
    @on(Button.Pressed, "#continue")
    def do_continue(self) -> None:
        selection = self.query_one("#resource-list", SelectionList)
        selected = list(selection.selected)
        self.app.pop_screen()
        if selected:
            self.callback(selected)
    
    def action_cancel(self) -> None:
        self.app.pop_screen()


class RegionSelectScreen(Screen):
    """Region selection screen."""
    
    BINDINGS = [("escape", "cancel", "Cancel")]
    
    def __init__(self, regions: list[str], callback):
        super().__init__()
        self.regions = regions
        self.callback = callback
    
    def compose(self) -> ComposeResult:
        with Container(id="select-dialog"):
            yield Static("Select region:", id="select-title")
            yield SelectionList[str](
                *[Selection(r, r, False) for r in self.regions],
                id="region-list"
            )
            with Horizontal(id="select-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Select", variant="primary", id="select")
    
    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.app.pop_screen()
    
    @on(Button.Pressed, "#select")
    def do_select(self) -> None:
        selection = self.query_one("#region-list", SelectionList)
        selected = list(selection.selected)
        self.app.pop_screen()
        if selected:
            self.callback(selected[0])
    
    def action_cancel(self) -> None:
        self.app.pop_screen()


class AWSwipeApp(App):
    """AWSwipe TUI Application."""
    
    CSS = """
    Screen { align: center middle; }
    #main-menu {
        width: 60;
        height: auto;
        border: solid red;
        padding: 1 2;
    }
    #title { text-align: center; text-style: bold; color: red; padding-bottom: 1; }
    #subtitle { text-align: center; color: grey; padding-bottom: 1; }
    Button { width: 100%; margin-bottom: 1; }
    #confirm-dialog, #select-dialog {
        width: 60;
        height: auto;
        border: solid red;
        padding: 2;
    }
    #confirm-message, #select-title { text-align: center; padding-bottom: 1; }
    #confirm-buttons, #select-buttons { align: center middle; height: 3; }
    #confirm-buttons Button, #select-buttons Button { width: auto; margin: 0 1; }
    #confirm-input { margin-bottom: 1; }
    SelectionList { height: 15; margin-bottom: 1; }
    #status { text-align: center; color: yellow; padding-top: 1; }
    """
    
    BINDINGS = [Binding("q", "quit", "Quit")]
    
    def __init__(self):
        super().__init__()
        setup_logging(verbosity=1)
    
    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-menu"):
            yield Static("AWSwipe", id="title")
            yield Static(f"run_id: {get_run_id()}", id="subtitle")
            yield Button("Preview (dry-run)", id="preview", variant="default")
            yield Button("Nuke single region", id="region", variant="warning")
            yield Button("NUKE ALL", id="nuke", variant="error")
            yield Button("Clean compute", id="compute", variant="primary")
            yield Button("Clean storage", id="storage", variant="primary")
            yield Button("Clean networking", id="network", variant="primary")
            yield Button("Clean dev/test only", id="devtest", variant="primary")
            yield Button("Custom selection", id="custom", variant="default")
            yield Button("Exit", id="exit")
            yield Static("", id="status")
        yield Footer()
    
    def set_status(self, msg: str) -> None:
        self.query_one("#status", Static).update(msg)
    
    @work(thread=True)
    def run_cleanup(self, config: Config) -> None:
        self.call_from_thread(self.set_status, "Running cleanup...")
        cleaner = SuperAWSResourceCleaner(config)
        cleaner.purge_aws()
        self.call_from_thread(self.set_status, "Done!")
    
    @on(Button.Pressed, "#exit")
    def do_exit(self) -> None:
        self.exit()
    
    @on(Button.Pressed, "#preview")
    def do_preview(self) -> None:
        config = Config()
        config.dry_run = True
        self.run_cleanup(config)
    
    @on(Button.Pressed, "#region")
    def do_region(self) -> None:
        cleaner = SuperAWSResourceCleaner(Config())
        regions = cleaner.get_all_regions()
        
        def on_region(region: str):
            def on_confirm():
                config = Config()
                config.dry_run = False
                config.regions = [region]
                self.run_cleanup(config)
            self.push_screen(ConfirmScreen(f"Delete ALL in {region}?", on_confirm))
        
        self.push_screen(RegionSelectScreen(regions, on_region))
    
    @on(Button.Pressed, "#nuke")
    def do_nuke(self) -> None:
        def on_confirm():
            config = Config()
            config.dry_run = False
            config.regions = ["all"]
            self.run_cleanup(config)
        self.push_screen(ConfirmScreen("DELETE EVERYTHING in ALL regions?", on_confirm))
    
    @on(Button.Pressed, "#compute")
    def do_compute(self) -> None:
        def on_confirm():
            config = Config()
            config.dry_run = False
            config.resource_types = ["ec2", "lambda", "eks", "autoscaling"]
            self.run_cleanup(config)
        self.push_screen(ConfirmScreen("Delete compute resources?", on_confirm))
    
    @on(Button.Pressed, "#storage")
    def do_storage(self) -> None:
        def on_confirm():
            config = Config()
            config.dry_run = False
            config.resource_types = ["s3", "ebs"]
            self.run_cleanup(config)
        self.push_screen(ConfirmScreen("Delete storage resources?", on_confirm))
    
    @on(Button.Pressed, "#network")
    def do_network(self) -> None:
        def on_confirm():
            config = Config()
            config.dry_run = False
            config.resource_types = ["vpc", "elb", "route53"]
            self.run_cleanup(config)
        self.push_screen(ConfirmScreen("Delete networking resources?", on_confirm))
    
    @on(Button.Pressed, "#devtest")
    def do_devtest(self) -> None:
        def on_confirm():
            config = Config()
            config.dry_run = False
            config.tag_filters.include = {"Environment": ["dev", "test", "sandbox"]}
            self.run_cleanup(config)
        self.push_screen(ConfirmScreen("Delete dev/test tagged resources?", on_confirm))
    
    @on(Button.Pressed, "#custom")
    def do_custom(self) -> None:
        def on_types(types: list[str]):
            def on_confirm():
                config = Config()
                config.dry_run = False
                config.resource_types = types
                self.run_cleanup(config)
            self.push_screen(ConfirmScreen(f"Delete: {', '.join(types)}?", on_confirm))
        self.push_screen(ResourceSelectScreen(on_types))


def run_interactive():
    """Entry point for interactive mode."""
    AWSwipeApp().run()
